// ast_scanner_go.go — Scan a Go project for usage of a target module.
//
// Usage:
//     go run ast_scanner_go.go <project_path> <module_path>
//
// Reads every .go file under <project_path> (excluding vendor/, testdata/,
// .git/, and common build output dirs), parses with go/parser, and reports:
//
//   1. import statements referring to <module_path> (or any /vN variant,
//      or any sub-package), with form (named / alias / dot / blank).
//   2. selector expressions that reference one of those imports.
//
// Symbol normalization (matches references/go_workflow.md):
//     import "github.com/foo/bar"        + bar.NewClient()  → github.com/foo/bar.NewClient
//     import b "github.com/foo/bar"      + b.Foo            → github.com/foo/bar.Foo
//     import . "github.com/foo/bar"      + Foo()            → github.com/foo/bar.Foo  (dot_import flagged)
//     import _ "github.com/foo/bar"                          → no symbol, blank_import flagged
//     import "github.com/foo/bar/v2"     + bar.Foo          → github.com/foo/bar/v2.Foo (path kept)
//     import "github.com/foo/bar/sub"    + sub.X            → github.com/foo/bar/sub.X (submodule flagged)
//
// Output JSON (aligned with ast_scanner_js.js / ast_scanner.py):
//   {
//     "scan_results": [   // [] when no matches — never null
//       {
//         "file": "src/foo.go",
//         "imports": [
//           {"type": "named", "module": "...", "alias": "bar",
//             "line": 3, "context": "..."}, ...
//         ],
//         "usages": [
//           {"symbol": "github.com/foo/bar.NewClient", "line": 12,
//             "context": "..."}, ...
//         ]
//       }, ...
//     ],
//     "total_files":   N,         // .go files walked
//     "files_scanned": N,         // alias of total_files for clarity
//     "import_count":  N,         // total import sites across all files
//     "usage_count":   N,         // total usage symbols across all files
//     "package_name":  "github.com/foo/bar",
//     "language":      "go",
//     "warnings":      [...],     // [] when none — never null
//     "verdict":       "zero_impact" | "has_impact" | "scan_errored",
//     "verdict_reason":"package is in module graph but no source file imports it"
//   }
//
// The `verdict` field exists so the skill (Phase 4) can short-circuit without
// re-deriving conclusions from the raw array. IMPROVEMENT.md §5.

package main

import (
	"encoding/json"
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"io/fs"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

// Top-level config — set from CLI args
var (
	projectPath string
	targetPath  string // user-provided, e.g. "github.com/foo/bar"
	targetBase  string // stripped of /vN suffix
)

// ------------------------------------------------------------------------- //
// Output types
// ------------------------------------------------------------------------- //

type ImportEntry struct {
	Type    string `json:"type"`   // "named" | "alias" | "dot_import" | "blank_import" | "submodule_import"
	Module  string `json:"module"` // resolved module path (with /vN if applicable)
	Alias   string `json:"alias"`  // local name used in this file
	Line    int    `json:"line"`
	Context string `json:"context"`
}

type UsageEntry struct {
	Symbol  string `json:"symbol"`
	Line    int    `json:"line"`
	Context string `json:"context"`
}

type FileResult struct {
	File    string        `json:"file"`
	Imports []ImportEntry `json:"imports"`
	Usages  []UsageEntry  `json:"usages"`
}

type Output struct {
	ScanResults   []FileResult `json:"scan_results"`
	TotalFiles    int          `json:"total_files"`
	FilesScanned  int          `json:"files_scanned"`
	ImportCount   int          `json:"import_count"`
	UsageCount    int          `json:"usage_count"`
	PackageName   string       `json:"package_name"`
	Language      string       `json:"language"`
	Warnings      []string     `json:"warnings"`
	Verdict       string       `json:"verdict"`
	VerdictReason string       `json:"verdict_reason"`
}

// ------------------------------------------------------------------------- //
// Path matching
// ------------------------------------------------------------------------- //

// stripMajorSuffix removes a trailing "/vN" (N >= 2) from a module path.
func stripMajorSuffix(p string) string {
	// Simplified: handle /v2 .. /v999
	if i := strings.LastIndex(p, "/v"); i > 0 {
		suffix := p[i+2:]
		if n, err := strconv.Atoi(suffix); err == nil && n >= 2 {
			return p[:i]
		}
	}
	return p
}

// matchesTarget returns the import classification, or empty if not a match.
//
// Matches when:
//   - importPath == targetBase                          (named)
//   - importPath == targetBase + "/vN" for any N>=2     (named)
//   - importPath has prefix targetBase + "/"            (submodule_import)
//   - importPath has prefix (targetBase + "/vN") + "/"  (submodule_import under vN)
func matchesTarget(importPath string) (matchType string, ok bool) {
	if importPath == targetBase {
		return "exact", true
	}
	// /vN suffix
	if stripMajorSuffix(importPath) == targetBase && importPath != targetBase {
		return "exact", true
	}
	// Submodule under base
	if strings.HasPrefix(importPath, targetBase+"/") {
		// Filter out the /vN case already handled above
		rest := importPath[len(targetBase)+1:]
		if n, err := strconv.Atoi(strings.TrimPrefix(rest, "v")); err == nil && n >= 2 && !strings.Contains(rest, "/") {
			return "exact", true
		}
		return "submodule", true
	}
	return "", false
}

// ------------------------------------------------------------------------- //
// Context (±5 lines)
// ------------------------------------------------------------------------- //

func getContext(lines []string, lineno int, radius int) string {
	start := lineno - radius - 1
	if start < 0 {
		start = 0
	}
	end := lineno + radius
	if end > len(lines) {
		end = len(lines)
	}
	var b strings.Builder
	for i := start; i < end; i++ {
		fmt.Fprintf(&b, "%4d | %s\n", i+1, lines[i])
	}
	return strings.TrimRight(b.String(), "\n")
}

// ------------------------------------------------------------------------- //
// File scanner
// ------------------------------------------------------------------------- //

var (
	skipDirs = map[string]bool{
		"vendor": true, "testdata": true, ".git": true,
		"node_modules": true, "dist": true, "build": true,
		"out": true, "examples": true, // examples often have unusual imports
	}
)

func isSourceFile(path string) bool {
	name := filepath.Base(path)
	if !strings.HasSuffix(name, ".go") {
		return false
	}
	// Skip generated files (often have very different shape; can give false matches)
	// Don't skip _test.go — test files often use the target package and the
	// LLM cares about test impact.
	return true
}

func walkProject(root string) ([]string, error) {
	var files []string
	err := filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return nil // best effort: skip inaccessible
		}
		if d.IsDir() {
			if skipDirs[d.Name()] {
				return filepath.SkipDir
			}
			return nil
		}
		if isSourceFile(path) {
			files = append(files, path)
		}
		return nil
	})
	return files, err
}

// ------------------------------------------------------------------------- //
// Per-file scan
// ------------------------------------------------------------------------- //

// scanFile parses one .go file. Returns (fileResult, hadDotImport, error).
//
// `hadDotImport` is bubbled up so the caller can warn (dot imports break
// our ability to resolve unqualified identifiers).
func scanFile(fpath string) (FileResult, bool, error) {
	src, err := os.ReadFile(fpath)
	if err != nil {
		return FileResult{}, false, err
	}
	lines := strings.Split(string(src), "\n")

	fset := token.NewFileSet()
	file, err := parser.ParseFile(fset, fpath, src, parser.ImportsOnly|parser.ParseComments)
	if err != nil {
		// ImportsOnly mode tolerates lots of syntactic noise; if it still fails,
		// we record the warning but try a full parse for usage scanning anyway.
		file, err = parser.ParseFile(fset, fpath, src, parser.ParseComments)
		if err != nil {
			return FileResult{
				File:    fpath,
				Imports: nil,
				Usages:  nil,
			}, false, err
		}
	} else {
		// Re-parse fully so usage scan has the body
		file, err = parser.ParseFile(fset, fpath, src, parser.ParseComments)
		if err != nil {
			return FileResult{File: fpath}, false, err
		}
	}

	// 1. Collect imports
	result := FileResult{File: fpath}
	// Map from local name → resolved import path (only for imports we care about).
	aliasToPath := map[string]string{}
	hadDotImport := false

	for _, imp := range file.Imports {
		path := strings.Trim(imp.Path.Value, `"`)
		matchKind, ok := matchesTarget(path)
		if !ok {
			continue
		}

		line := fset.Position(imp.Pos()).Line
		entry := ImportEntry{
			Module:  path,
			Line:    line,
			Context: getContext(lines, line, 3),
		}
		// Classify based on name
		var localName string
		if imp.Name != nil {
			switch imp.Name.Name {
			case ".":
				entry.Type = "dot_import"
				entry.Alias = "."
				hadDotImport = true
			case "_":
				entry.Type = "blank_import"
				entry.Alias = "_"
				// blank imports contribute nothing to symbol scanning
				result.Imports = append(result.Imports, entry)
				continue
			default:
				entry.Type = "alias"
				entry.Alias = imp.Name.Name
				localName = imp.Name.Name
			}
		} else {
			// Default name = last path segment, MINUS any /vN suffix
			localName = defaultPackageName(path)
			if matchKind == "submodule" {
				entry.Type = "submodule_import"
			} else {
				entry.Type = "named"
			}
			entry.Alias = localName
		}

		if matchKind == "submodule" && entry.Type == "" {
			entry.Type = "submodule_import"
		}

		// Track alias for usage scan
		if entry.Type == "dot_import" {
			// Use special marker — empty local name (handled below)
			aliasToPath["."] = path
		} else if localName != "" && entry.Type != "blank_import" {
			aliasToPath[localName] = path
		}

		result.Imports = append(result.Imports, entry)
	}

	// 2. Walk AST for selector expressions
	if len(aliasToPath) > 0 {
		dotPath := aliasToPath["."]
		hasDot := dotPath != ""

		ast.Inspect(file, func(n ast.Node) bool {
			if n == nil {
				return false
			}
			switch x := n.(type) {
			case *ast.SelectorExpr:
				// Try to resolve `Pkg.Sym` (where Pkg is one of our import aliases).
				// We accept: ident.Sym  OR  ident.Inner.Sym (one deeper, for `b.Inner.Method`)
				symbol, line := resolveSelector(x, aliasToPath, fset)
				if symbol != "" {
					result.Usages = append(result.Usages, UsageEntry{
						Symbol:  symbol,
						Line:    line,
						Context: getContext(lines, line, 5),
					})
				}
			case *ast.Ident:
				// Only relevant when there's a dot import in scope.
				// Heuristic: treat each *Ident* (capitalized = likely exported)
				// at a non-decl position as a candidate.
				if !hasDot {
					return true
				}
				// Skip non-exported names (lowercase first letter)
				if x.Name == "" || !isUpperASCII(x.Name[0]) {
					return true
				}
				// Skip if it has an Obj that points to a same-file declaration
				if x.Obj != nil && x.Obj.Decl != nil {
					return true
				}
				line := fset.Position(x.Pos()).Line
				result.Usages = append(result.Usages, UsageEntry{
					Symbol:  dotPath + "." + x.Name,
					Line:    line,
					Context: getContext(lines, line, 5),
				})
			}
			return true
		})
	}

	return result, hadDotImport, nil
}

func isUpperASCII(b byte) bool { return b >= 'A' && b <= 'Z' }

// defaultPackageName returns the "default" identifier under which a Go
// import becomes addressable. Per spec it's the package's `package`
// declaration, which we can't see without parsing the dep. Heuristic:
// strip /vN suffix and take the last path segment.
//
// This matches the common case (package name == last path segment) and
// is what go/parser would do absent compile-time resolution.
func defaultPackageName(path string) string {
	p := stripMajorSuffix(path)
	if i := strings.LastIndex(p, "/"); i >= 0 {
		return p[i+1:]
	}
	return p
}

// resolveSelector tries to interpret a SelectorExpr as `pkg.Sym` or
// `pkg.Inner.Sym`. Returns ("", 0) if neither matches.
func resolveSelector(
	sel *ast.SelectorExpr,
	aliasToPath map[string]string,
	fset *token.FileSet,
) (symbol string, line int) {
	// Case 1: X is *ast.Ident — `pkg.Sym`
	if ident, ok := sel.X.(*ast.Ident); ok {
		if path, found := aliasToPath[ident.Name]; found {
			return path + "." + sel.Sel.Name, fset.Position(sel.Pos()).Line
		}
		return "", 0
	}
	// Case 2: X is *ast.SelectorExpr — `pkg.Inner.Sym`
	if inner, ok := sel.X.(*ast.SelectorExpr); ok {
		if rootIdent, ok2 := inner.X.(*ast.Ident); ok2 {
			if path, found := aliasToPath[rootIdent.Name]; found {
				return path + "." + inner.Sel.Name + "." + sel.Sel.Name,
					fset.Position(sel.Pos()).Line
			}
		}
	}
	return "", 0
}

// ------------------------------------------------------------------------- //
// Main
// ------------------------------------------------------------------------- //

func main() {
	if len(os.Args) < 3 {
		fmt.Fprintln(os.Stderr, "Usage: go run ast_scanner_go.go <project_path> <module_path>")
		os.Exit(1)
	}
	projectPath = os.Args[1]
	targetPath = os.Args[2]
	targetBase = stripMajorSuffix(targetPath)

	files, err := walkProject(projectPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "walk error: %v\n", err)
		os.Exit(1)
	}

	// Initialize slices to non-nil so JSON encoding produces `[]` not `null`.
	out := Output{
		PackageName: targetPath,
		Language:    "go",
		ScanResults: []FileResult{},
		Warnings:    []string{},
	}

	parseErrors := 0
	for _, f := range files {
		res, hadDot, err := scanFile(f)
		if err != nil {
			out.Warnings = append(out.Warnings, fmt.Sprintf("parse failed: %s: %v", f, err))
			parseErrors++
			continue
		}
		if len(res.Imports) == 0 && len(res.Usages) == 0 {
			continue
		}
		// Make file path relative to project root for readability
		if rel, err := filepath.Rel(projectPath, f); err == nil {
			res.File = rel
		}
		out.ScanResults = append(out.ScanResults, res)
		out.ImportCount += len(res.Imports)
		out.UsageCount += len(res.Usages)
		if hadDot {
			out.Warnings = append(out.Warnings, fmt.Sprintf(
				"dot import detected in %s — usage scanning is best-effort; review manually",
				res.File))
		}
	}
	out.TotalFiles = len(files)
	out.FilesScanned = len(files)

	// Compute verdict from the totals.
	switch {
	case out.ImportCount == 0 && out.UsageCount == 0 && parseErrors == 0:
		out.Verdict = "zero_impact"
		out.VerdictReason = fmt.Sprintf(
			"scanned %d .go files; no import or usage of %s found",
			out.FilesScanned, targetPath,
		)
	case out.ImportCount == 0 && out.UsageCount == 0 && parseErrors > 0:
		out.Verdict = "scan_errored"
		out.VerdictReason = fmt.Sprintf(
			"%d file(s) failed to parse; no matches in the remaining %d. Treat as inconclusive.",
			parseErrors, out.FilesScanned-parseErrors,
		)
	default:
		out.Verdict = "has_impact"
		out.VerdictReason = fmt.Sprintf(
			"%d import site(s) and %d usage(s) found across %d file(s)",
			out.ImportCount, out.UsageCount, len(out.ScanResults),
		)
	}

	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	if err := enc.Encode(out); err != nil {
		fmt.Fprintf(os.Stderr, "encode error: %v\n", err)
		os.Exit(1)
	}
}
