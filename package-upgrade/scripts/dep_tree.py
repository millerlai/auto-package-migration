#!/usr/bin/env python3
"""Dependency tree analyzer for package upgrades.

Usage: python dep_tree.py <project_path> <package_name> [--pkg-manager pip|poetry|uv]
Output: JSON with dependency classification and tree information
"""

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def get_dep_tree_pip(project_path: str) -> Dict[str, Any]:
    """Get dependency tree using pipdeptree."""
    try:
        result = subprocess.run(
            ["pipdeptree", "--json-tree"],
            capture_output=True,
            text=True,
            cwd=project_path,
            check=True
        )
        return {"data": json.loads(result.stdout), "format": "json"}
    except subprocess.CalledProcessError as e:
        return {"error": f"pipdeptree failed: {e.stderr}", "data": []}
    except FileNotFoundError:
        return {"error": "pipdeptree not installed. Run: pip install pipdeptree", "data": []}


def get_dep_tree_poetry(project_path: str) -> Dict[str, Any]:
    """Get dependency tree using poetry show."""
    try:
        result = subprocess.run(
            ["poetry", "show", "--tree", "--no-ansi"],
            capture_output=True,
            text=True,
            cwd=project_path,
            check=True
        )
        return {"raw": result.stdout, "format": "text"}
    except subprocess.CalledProcessError as e:
        return {"error": f"poetry failed: {e.stderr}", "raw": ""}
    except FileNotFoundError:
        return {"error": "poetry not installed", "raw": ""}


def get_dep_tree_uv(project_path: str) -> Dict[str, Any]:
    """Get dependency tree using uv pip tree."""
    try:
        result = subprocess.run(
            ["uv", "pip", "tree"],
            capture_output=True,
            text=True,
            cwd=project_path,
            check=True
        )
        return {"raw": result.stdout, "format": "text"}
    except subprocess.CalledProcessError as e:
        return {"error": f"uv failed: {e.stderr}", "raw": ""}
    except FileNotFoundError:
        return {"error": "uv not installed", "raw": ""}


def get_installed_version(package_name: str, pkg_manager: str, project_path: str) -> str:
    """Get the currently installed version of a package."""
    cmds = {
        "pip": ["pip", "show", package_name],
        "poetry": ["poetry", "show", package_name],
        "uv": ["uv", "pip", "show", package_name],
    }

    try:
        result = subprocess.run(
            cmds.get(pkg_manager, cmds["pip"]),
            capture_output=True,
            text=True,
            cwd=project_path
        )
        for line in result.stdout.splitlines():
            if line.lower().startswith("version:"):
                return line.split(":", 1)[1].strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    return "unknown"


def find_parents_in_tree(package_name: str, tree_data: Any, format_type: str = "json") -> Tuple[List[str], Dict[str, str]]:
    """Recursively search dependency tree to find parent packages.

    Returns:
        Tuple of (parent_packages, version_constraints)
    """
    parents = []
    constraints = {}

    if format_type == "json" and isinstance(tree_data, dict):
        data = tree_data.get("data", [])
        if isinstance(data, list):
            for pkg in data:
                _search_json_tree(package_name.lower(), pkg, parents, constraints)

    return parents, constraints


def _search_json_tree(target: str, node: Dict, parents: List[str], constraints: Dict[str, str], parent_name: Optional[str] = None):
    """Helper to recursively search JSON tree structure."""
    pkg_name = node.get("package_name", node.get("key", "")).lower()

    # Check dependencies of current node
    dependencies = node.get("dependencies", [])
    for dep in dependencies:
        dep_name = dep.get("package_name", dep.get("key", "")).lower()
        if dep_name == target:
            # Found target as dependency
            if pkg_name and pkg_name not in parents:
                parents.append(pkg_name)
                # Try to extract version constraint
                installed_ver = dep.get("installed_version", "")
                required_ver = dep.get("required_version", "")
                if required_ver:
                    constraints[pkg_name] = required_ver
                elif installed_ver:
                    constraints[pkg_name] = f"=={installed_ver}"

        # Recurse into dependency's dependencies
        if dep.get("dependencies"):
            _search_json_tree(target, dep, parents, constraints, pkg_name)


def classify_dependency(
    package_name: str,
    dep_tree: Dict[str, Any],
    dep_files: List[str],
    format_type: str = "json"
) -> Dict[str, Any]:
    """Classify package as direct, transitive, or both dependency."""
    is_direct = False
    parent_packages = []
    version_constraints = {}

    # Check if package is directly declared in dependency files
    package_pattern = re.compile(rf'^{re.escape(package_name)}\b', re.MULTILINE | re.IGNORECASE)

    for dep_file in dep_files:
        try:
            content = Path(dep_file).read_text()
            if package_pattern.search(content):
                is_direct = True
                break
        except (FileNotFoundError, IOError):
            continue

    # Find parent packages from dependency tree
    parent_packages, version_constraints = find_parents_in_tree(
        package_name, dep_tree, format_type
    )

    is_transitive = len(parent_packages) > 0

    # Determine dependency type
    if is_direct and is_transitive:
        dep_type = "both"
    elif is_direct:
        dep_type = "direct"
    elif is_transitive:
        dep_type = "transitive"
    else:
        dep_type = "unknown"

    return {
        "dependency_type": dep_type,
        "is_direct": is_direct,
        "is_transitive": is_transitive,
        "parent_packages": parent_packages,
        "version_constraints": version_constraints,
    }


def main():
    parser = argparse.ArgumentParser(description="Analyze dependency tree for a package")
    parser.add_argument("project_path", help="Path to the project directory")
    parser.add_argument("package_name", help="Name of the package to analyze")
    parser.add_argument("--pkg-manager", choices=["pip", "poetry", "uv"], default="pip",
                       help="Package manager to use")
    args = parser.parse_args()

    # Get dependency tree based on package manager
    tree_funcs = {
        "pip": get_dep_tree_pip,
        "poetry": get_dep_tree_poetry,
        "uv": get_dep_tree_uv
    }

    dep_tree = tree_funcs[args.pkg_manager](args.project_path)
    format_type = dep_tree.get("format", "json")

    # Get installed version
    version = get_installed_version(args.package_name, args.pkg_manager, args.project_path)

    # Find dependency files
    dep_files_raw = subprocess.run(
        [
            "find", args.project_path, "-maxdepth", "2",
            "(", "-name", "requirements*.txt", "-o", "-name", "pyproject.toml",
            "-o", "-name", "setup.py", "-o", "-name", "setup.cfg", ")",
            "-not", "-path", "*/.venv/*",
            "-not", "-path", "*/venv/*"
        ],
        capture_output=True,
        text=True
    )
    dep_files = [f for f in dep_files_raw.stdout.strip().splitlines() if f]

    # Classify dependency
    classification = classify_dependency(
        args.package_name,
        dep_tree,
        dep_files,
        format_type
    )

    # Build result
    result = {
        "package_name": args.package_name,
        "current_version": version,
        **classification,
        "full_tree": dep_tree,
    }

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
