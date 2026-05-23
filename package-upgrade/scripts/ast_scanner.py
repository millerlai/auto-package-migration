#!/usr/bin/env python3
"""AST scanner for package usage analysis.

Usage: python ast_scanner.py <project_path> <package_name>
Output: JSON with all imports and usages of the target package
"""

import ast
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


class PackageUsageVisitor(ast.NodeVisitor):
    """AST visitor to track package imports and usage."""

    def __init__(self, package_name: str, source_lines: List[str]):
        self.package_name = package_name
        self.source_lines = source_lines
        self.imports = []       # Import statements
        self.usages = []        # Symbol usage locations
        self.imported_names = {} # Maps local name -> original module path

    def visit_Import(self, node: ast.Import):
        """Track 'import module' statements."""
        for alias in node.names:
            if alias.name == self.package_name or alias.name.startswith(f"{self.package_name}."):
                local_name = alias.asname or alias.name
                self.imported_names[local_name] = alias.name
                self.imports.append({
                    "type": "import",
                    "module": alias.name,
                    "alias": alias.asname,
                    "line": node.lineno,
                    "context": self._get_context(node.lineno),
                })
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        """Track 'from module import name' statements."""
        if node.module and (
            node.module == self.package_name
            or node.module.startswith(f"{self.package_name}.")
        ):
            for alias in node.names:
                local_name = alias.asname or alias.name
                full_name = f"{node.module}.{alias.name}" if alias.name != "*" else node.module
                self.imported_names[local_name] = full_name
                self.imports.append({
                    "type": "from_import",
                    "module": node.module,
                    "name": alias.name,
                    "alias": alias.asname,
                    "line": node.lineno,
                    "context": self._get_context(node.lineno),
                })
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        """Track attribute access like obj.method()."""
        chain = self._resolve_attr_chain(node)
        if chain:
            root = chain.split(".")[0]
            if root in self.imported_names:
                full_name = self.imported_names[root] + chain[len(root):]
                self.usages.append({
                    "symbol": full_name,
                    "line": node.lineno,
                    "context": self._get_context(node.lineno),
                })
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name):
        """Track name references."""
        if node.id in self.imported_names:
            self.usages.append({
                "symbol": self.imported_names[node.id],
                "line": node.lineno,
                "context": self._get_context(node.lineno),
            })
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
        return "\n".join(
            f"{start + i + 1:4d} | {line}"
            for i, line in enumerate(lines)
        )


def scan_file(filepath: Path, package_name: str) -> Optional[Dict[str, Any]]:
    """Scan a single Python file for package usage."""
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))
    except (SyntaxError, UnicodeDecodeError):
        # Skip files with syntax errors or encoding issues
        return None

    visitor = PackageUsageVisitor(package_name, source.splitlines())
    visitor.visit(tree)

    # Only return if the file actually uses the package
    if not visitor.imports and not visitor.usages:
        return None

    return {
        "file": str(filepath),
        "imports": visitor.imports,
        "usages": visitor.usages,
    }


def scan_project(project_path: str, package_name: str) -> List[Dict[str, Any]]:
    """Scan entire project for package usage."""
    results = []
    project_root = Path(project_path)

    # Skip these directories
    skip_dirs = {'.git', '__pycache__', '.venv', 'venv', 'node_modules', '.tox', '.pytest_cache'}

    for py_file in project_root.rglob("*.py"):
        # Check if any parent directory should be skipped
        if any(part in skip_dirs or part.startswith('.') for part in py_file.parts):
            continue

        result = scan_file(py_file, package_name)
        if result:
            results.append(result)

    return results


def main():
    if len(sys.argv) < 3:
        print("Usage: python ast_scanner.py <project_path> <package_name>", file=sys.stderr)
        sys.exit(1)

    project_path = sys.argv[1]
    package_name = sys.argv[2]

    results = scan_project(project_path, package_name)

    output = {
        "scan_results": results,
        "total_files": len(results),
        "package_name": package_name,
    }

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
