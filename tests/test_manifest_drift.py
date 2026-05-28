"""Guard against verify_installation.sh drifting from the actual skill tree.

verify_installation.sh keeps a hand-written manifest of every helper script and
reference doc that a correct install must contain (its `check_scripts` /
`check_refs` calls). That manifest is the one place we deliberately list files
by name — a pure `find` scan can only prove "what exists runs", never "what
should exist is present". The cost of a hand-written list is that a refactor
(move / rename / add / delete a file) can leave it stale, which is exactly how
the per-language reorg broke the script earlier.

This test makes that drift fail loudly: it parses the manifest out of the shell
script and compares it, in both directions, against the files actually on disk.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERIFY = ROOT / "verify_installation.sh"
SKILL = ROOT / "package-upgrade"

# verify lists these as executable/loadable helpers; .json (package metadata),
# node_modules, and __pycache__ are intentionally not part of the manifest.
SCRIPT_EXTS = {".sh", ".py", ".js", ".go"}
REF_EXTS = {".md"}
IGNORE_DIRS = {"node_modules", "__pycache__"}


def _parse_manifest(func_name: str) -> dict[str, set[str]]:
    """Extract {subdir: {filenames}} from check_scripts / check_refs calls.

    Calls use backslash line-continuations, so join those first, then match
    `<func_name> <subdir> <file> <file> ...`. The function *definition*
    (`check_scripts() {`) has no space before `(` so it never matches.
    """
    text = VERIFY.read_text(encoding="utf-8")
    joined = re.sub(r"\\\n\s*", " ", text)
    manifest: dict[str, set[str]] = {}
    pattern = re.compile(rf"^{func_name}\s+(\S+)\s+(.+)$")
    for line in joined.splitlines():
        line = line.strip()
        if line.startswith("#"):
            continue
        m = pattern.match(line)
        if not m:
            continue
        subdir, rest = m.group(1), m.group(2)
        manifest.setdefault(subdir, set()).update(rest.split())
    return manifest


def _actual(base: Path, exts: set[str]) -> dict[str, set[str]]:
    """Return {subdir: {filenames}} actually on disk (one level deep)."""
    actual: dict[str, set[str]] = {}
    for sub in base.iterdir():
        if not sub.is_dir() or sub.name in IGNORE_DIRS:
            continue
        actual[sub.name] = {f.name for f in sub.iterdir() if f.is_file() and f.suffix in exts}
    return actual


def _assert_no_drift(kind: str, manifest: dict[str, set[str]], actual: dict[str, set[str]]) -> None:
    # 1. Same set of language subdirs (catches a whole new subdir verify forgot).
    assert set(manifest) == set(actual), (
        f"{kind}: subdir set differs between verify_installation.sh and disk.\n"
        f"  only in verify: {sorted(set(manifest) - set(actual))}\n"
        f"  only on disk:   {sorted(set(actual) - set(manifest))}"
    )
    # 2. Per-subdir two-direction file diff.
    problems = []
    for sub in sorted(manifest):
        listed, present = manifest[sub], actual[sub]
        missing = present - listed  # on disk, not verified -> verify is stale
        ghost = listed - present  # verified, not on disk -> verify is wrong
        if missing:
            problems.append(f"  {sub}/: on disk but NOT in verify: {sorted(missing)}")
        if ghost:
            problems.append(f"  {sub}/: in verify but NOT on disk: {sorted(ghost)}")
    assert not problems, (
        f"{kind}: verify_installation.sh manifest drifted from disk.\n"
        + "\n".join(problems)
        + "\nUpdate the check_scripts/check_refs lists in verify_installation.sh."
    )


def test_scripts_manifest_matches_disk() -> None:
    _assert_no_drift(
        "scripts",
        _parse_manifest("check_scripts"),
        _actual(SKILL / "scripts", SCRIPT_EXTS),
    )


def test_references_manifest_matches_disk() -> None:
    _assert_no_drift(
        "references",
        _parse_manifest("check_refs"),
        _actual(SKILL / "references", REF_EXTS),
    )
