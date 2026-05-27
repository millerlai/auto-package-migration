#!/usr/bin/env python3
"""AST scanner for package usage analysis.

Usage: python ast_scanner.py <project_path> <package_name>

Output JSON (aligned with ast_scanner_js.js / ast_scanner_go.go):
  {
    "scan_results": [...],        // [] when no matches — never null
    "total_files": N,             // .py files walked
    "files_scanned": N,           // alias of total_files for clarity
    "import_count": N,            // total import sites across all files
    "usage_count": N,             // total usage symbols across all files
    "package_name": "...",
    "language": "python",
    "warnings": [...],            // [] when none
    "verdict": "zero_impact" | "has_impact" | "scan_errored",
    "verdict_reason": "..."
  }

The `verdict` field lets the skill (Phase 4) short-circuit without
re-deriving conclusions from the raw array. Matches the schema first
introduced in ast_scanner_go.go.
"""

import ast
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class PackageUsageVisitor(ast.NodeVisitor):
    """AST visitor to track package imports and usage."""

    def __init__(self, package_name: str, source_lines: List[str]):
        self.package_name = package_name
        self.source_lines = source_lines
        self.imports = []  # Import statements
        self.usages = []  # Symbol usage locations
        self.imported_names = {}  # Maps local name -> original module path

    def visit_Import(self, node: ast.Import):
        """Track 'import module' statements."""
        for alias in node.names:
            if alias.name == self.package_name or alias.name.startswith(f"{self.package_name}."):
                local_name = alias.asname or alias.name
                self.imported_names[local_name] = alias.name
                self.imports.append(
                    {
                        "type": "import",
                        "module": alias.name,
                        "alias": alias.asname,
                        "line": node.lineno,
                        "context": self._get_context(node.lineno),
                    }
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        """Track 'from module import name' statements."""
        if node.module and (
            node.module == self.package_name or node.module.startswith(f"{self.package_name}.")
        ):
            for alias in node.names:
                local_name = alias.asname or alias.name
                full_name = f"{node.module}.{alias.name}" if alias.name != "*" else node.module
                self.imported_names[local_name] = full_name
                self.imports.append(
                    {
                        "type": "from_import",
                        "module": node.module,
                        "name": alias.name,
                        "alias": alias.asname,
                        "line": node.lineno,
                        "context": self._get_context(node.lineno),
                    }
                )
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        """Track attribute access like obj.method()."""
        chain = self._resolve_attr_chain(node)
        if chain:
            root = chain.split(".")[0]
            if root in self.imported_names:
                full_name = self.imported_names[root] + chain[len(root) :]
                self.usages.append(
                    {
                        "symbol": full_name,
                        "line": node.lineno,
                        "context": self._get_context(node.lineno),
                    }
                )
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name):
        """Track name references."""
        if node.id in self.imported_names:
            self.usages.append(
                {
                    "symbol": self.imported_names[node.id],
                    "line": node.lineno,
                    "context": self._get_context(node.lineno),
                }
            )
        self.generic_visit(node)

    def _resolve_attr_chain(self, node: ast.AST) -> Optional[str]:
        """Resolve attribute chain like obj.method.attr to string."""
        parts = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            parts.append(node.id)
            return ".".join(reversed(parts))
        return None

    def _get_context(self, lineno: int, radius: int = 5) -> str:
        """Get code context around a line number (±radius lines)."""
        start = max(0, lineno - radius - 1)
        end = min(len(self.source_lines), lineno + radius)
        lines = self.source_lines[start:end]
        return "\n".join(f"{start + i + 1:4d} | {line}" for i, line in enumerate(lines))


def _scan_file_internal(filepath: Path, package_name: str) -> Tuple[Optional[Dict[str, Any]], bool]:
    """Scan a single Python file for package usage.

    Returns (result_or_None, parse_failed). `parse_failed` is True when the
    file was unreadable or unparseable; the caller needs this to distinguish
    `zero_impact` (clean walk, no match) from `scan_errored` (couldn't parse).
    """
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))
    except (SyntaxError, UnicodeDecodeError):
        return None, True

    visitor = PackageUsageVisitor(package_name, source.splitlines())
    visitor.visit(tree)

    if not visitor.imports and not visitor.usages:
        return None, False

    return {
        "file": str(filepath),
        "imports": visitor.imports,
        "usages": visitor.usages,
    }, False


def scan_file(filepath: Path, package_name: str) -> Optional[Dict[str, Any]]:
    """Scan a single Python file for package usage.

    Backwards-compatible wrapper that hides the parse-failed flag.
    """
    result, _ = _scan_file_internal(filepath, package_name)
    return result


# Skip these directories during project walk.
_SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".tox", ".pytest_cache"}


def _walk_python_files(project_path: str):
    """Yield .py files under project_path, skipping ignored directories."""
    project_root = Path(project_path)
    for py_file in project_root.rglob("*.py"):
        if any(part in _SKIP_DIRS or part.startswith(".") for part in py_file.parts):
            continue
        yield py_file


def scan_project_stats(
    project_path: str, package_name: str
) -> Tuple[List[Dict[str, Any]], int, int]:
    """Walk project, return (matching_results, files_scanned, parse_errors)."""
    results: List[Dict[str, Any]] = []
    files_scanned = 0
    parse_errors = 0
    for py_file in _walk_python_files(project_path):
        files_scanned += 1
        result, parse_failed = _scan_file_internal(py_file, package_name)
        if parse_failed:
            parse_errors += 1
        elif result:
            results.append(result)
    return results, files_scanned, parse_errors


def scan_project(project_path: str, package_name: str) -> List[Dict[str, Any]]:
    """Scan entire project for package usage (results only — back-compat)."""
    results, _, _ = scan_project_stats(project_path, package_name)
    return results


def compute_verdict(
    results: List[Dict[str, Any]],
    files_scanned: int,
    parse_errors: int,
    package_name: str,
) -> Tuple[str, str, int, int]:
    """Mirror ast_scanner_go.go verdict logic.

    Returns (verdict, verdict_reason, import_count, usage_count).
    """
    import_count = sum(len(r["imports"]) for r in results)
    usage_count = sum(len(r["usages"]) for r in results)

    if import_count == 0 and usage_count == 0 and parse_errors == 0:
        return (
            "zero_impact",
            f"scanned {files_scanned} .py file(s); no import or usage of " f"{package_name} found",
            import_count,
            usage_count,
        )
    if import_count == 0 and usage_count == 0 and parse_errors > 0:
        return (
            "scan_errored",
            f"{parse_errors} file(s) failed to parse; no matches in the "
            f"remaining {files_scanned - parse_errors}. Treat as inconclusive.",
            import_count,
            usage_count,
        )
    return (
        "has_impact",
        f"{import_count} import site(s) and {usage_count} usage(s) found "
        f"across {len(results)} file(s)",
        import_count,
        usage_count,
    )


def main():
    if len(sys.argv) < 3:
        print("Usage: python ast_scanner.py <project_path> <package_name>", file=sys.stderr)
        sys.exit(1)

    project_path = sys.argv[1]
    package_name = sys.argv[2]

    results, files_scanned, parse_errors = scan_project_stats(project_path, package_name)
    verdict, verdict_reason, import_count, usage_count = compute_verdict(
        results, files_scanned, parse_errors, package_name
    )

    warnings: List[str] = []
    if parse_errors > 0:
        warnings.append(f"{parse_errors} file(s) failed to parse; results may be incomplete")

    output = {
        "scan_results": results,
        "total_files": files_scanned,
        "files_scanned": files_scanned,
        "import_count": import_count,
        "usage_count": usage_count,
        "package_name": package_name,
        "language": "python",
        "warnings": warnings,
        "verdict": verdict,
        "verdict_reason": verdict_reason,
    }

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
