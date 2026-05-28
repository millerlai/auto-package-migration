#!/usr/bin/env python3
"""Parse yarn/npm/pnpm output into categorised errors.

Usage:
    python3 parse_pm_errors.py [--pkg-manager yarn|npm|pnpm] [<file>]

Reads pkg-manager output from <file> (or stdin) and classifies errors into:
- auth     : registry authentication failure (e.g. YN0041, 401, E401)
- patch    : yarn berry builtin patch failures (usually noise — YN0066)
- network  : DNS/proxy/timeout/connection errors
- conflict : peer dep / version range conflicts (ERESOLVE, YN0086, etc.)
- checksum : integrity mismatch (EINTEGRITY, YN0018, sha mismatch)
- missing  : package not found in registry (E404, YN0035, ERR_PACKAGE_NOT_FOUND)

The "primary_blocker" field is the LLM's hint for which follow-up to ask.

Output JSON:
{
  "categories": {
    "auth":     [{"pkg": "...", "registry": "...", "code": "YN0041", "raw": "..."}],
    "patch":    [{"pkg": "...", "code": "YN0066", "noise": true, "raw": "..."}],
    "network":  [...],
    "conflict": [...],
    "checksum": [...],
    "missing":  [...]
  },
  "primary_blocker": "auth" | "network" | "conflict" | "checksum" | "missing" | "patch" | null,
  "remediation": "Need JFROG_TOKEN (see auth_tokens.md)",
  "exit_clue": "the rest of the output is likely follow-on errors caused by the blocker"
}
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Dict, List, Optional, Tuple

# ---------- pattern catalogues ----------

# Auth failures
AUTH_PATTERNS = [
    re.compile(r"YN0041:.*?(?:Invalid authentication|authentication required)", re.I),
    re.compile(r"\bE401\b"),
    re.compile(r"\b401 Unauthorized\b"),
    re.compile(r"\b403 Forbidden\b"),
    re.compile(r"authentication required"),
    re.compile(r"authentication failed", re.I),
    re.compile(r"incorrect or missing password", re.I),
    re.compile(r"ENEEDAUTH"),
]

# Patch noise (Yarn berry tries to patch certain packages like typescript)
PATCH_PATTERNS = [
    re.compile(r"YN0066:"),
    re.compile(r"patch failed", re.I),
    re.compile(r"Cannot apply patch", re.I),
]

# Network
NETWORK_PATTERNS = [
    re.compile(r"YN0050:"),
    re.compile(r"\bENOTFOUND\b"),
    re.compile(r"\bECONNREFUSED\b"),
    re.compile(r"\bETIMEDOUT\b"),
    re.compile(r"\bEAI_AGAIN\b"),
    re.compile(r"\bgetaddrinfo\b"),
    re.compile(r"\bnetwork error\b", re.I),
    re.compile(r"\brequest to .* failed\b", re.I),
    re.compile(r"tunneling socket could not be established", re.I),
]

# Version / conflict
CONFLICT_PATTERNS = [
    re.compile(r"\bERESOLVE\b"),
    re.compile(r"unable to resolve dependency tree", re.I),
    re.compile(r"YN0002:"),  # missing peer
    re.compile(r"YN0060:"),  # incompatible peer
    re.compile(r"YN0086:"),  # immutable lockfile mismatch
    re.compile(r"peer dep(?:endency)? missing", re.I),
    re.compile(r"No candidates? found", re.I),
]

# Checksum / integrity
CHECKSUM_PATTERNS = [
    re.compile(r"\bEINTEGRITY\b"),
    re.compile(r"YN0018:"),
    re.compile(r"sha\d+ checksum mismatch", re.I),
    re.compile(r"integrity checksum failed", re.I),
    re.compile(r"cache key mismatch", re.I),
]

# Package missing in registry
MISSING_PATTERNS = [
    re.compile(r"\bE404\b"),
    re.compile(r"\b404 Not Found\b"),
    re.compile(r"YN0035:"),
    re.compile(r"No matching version found", re.I),
    re.compile(r"is not in the npm registry", re.I),
    re.compile(r"ERR_PACKAGE_NOT_FOUND", re.I),
]

# Heuristic: extract the package name from a yarn YN0041 line.
# Typical format: "└─ @scope/pkg@npm:1.2.3 (resolution: ...)"
PKG_EXTRACT_PATTERNS = [
    re.compile(r"((?:@[\w\-]+/)?[\w\-]+)@npm:([\w\-.]+)"),
    re.compile(r'package[ -]?[`"]?((?:@[\w\-]+/)?[\w\-]+)[`"]?', re.I),
    re.compile(r"((?:@[\w\-]+/)?[\w\-]+)@\^?[\w\-.]+"),
]

# Registry host hint
REGISTRY_PATTERNS = [
    re.compile(r"https?://([^/\s\)]+)"),
]

# Map category → remediation hint
REMEDIATION = {
    "auth": "Need a token for the failing registry. Re-run preflight.sh to identify which env var is required (see auth_tokens.md).",
    "network": "Check VPN / proxy / DNS for the failing registry host. The registry server may also be down.",
    "conflict": "Peer / version conflict. Re-check Phase 2 dependency tree; you may need to also upgrade the parent package that pins the conflicting range.",
    "checksum": "Lockfile integrity mismatch. Either the upstream package was republished (revert and rerun) or a manual lockfile edit got the checksum wrong. Run validate_lockfile.sh.",
    "missing": "Target version doesn't exist in the registry. Double-check the version string or check whether the package was unpublished.",
    "patch": "Yarn's builtin patch failed (e.g. for typescript). USUALLY harmless / noise; check for OTHER errors first before treating as primary.",
}

# Priority order: when multiple categories fire, this picks the one most likely
# to be the actual root cause. `patch` is intentionally last because it's
# usually noise piggy-backing on a real failure.
BLOCKER_PRIORITY = ["auth", "checksum", "missing", "conflict", "network", "patch"]


def extract_pkg_and_registry(line: str) -> Tuple[Optional[str], Optional[str]]:
    pkg = None
    for pat in PKG_EXTRACT_PATTERNS:
        m = pat.search(line)
        if m:
            pkg = m.group(1)
            break
    registry = None
    for pat in REGISTRY_PATTERNS:
        m = pat.search(line)
        if m:
            registry = m.group(1)
            break
    return pkg, registry


def classify(output: str) -> Dict:
    categories: Dict[str, List[Dict]] = {
        "auth": [],
        "patch": [],
        "network": [],
        "conflict": [],
        "checksum": [],
        "missing": [],
    }
    # Group multi-line errors: a "block" is a contiguous run of indented or
    # bullet-prefixed lines following an error marker. For simplicity we
    # classify line-by-line and dedupe by (category, raw[:120]).
    seen = set()

    catalogue = [
        ("auth", AUTH_PATTERNS),
        ("patch", PATCH_PATTERNS),
        ("network", NETWORK_PATTERNS),
        ("conflict", CONFLICT_PATTERNS),
        ("checksum", CHECKSUM_PATTERNS),
        ("missing", MISSING_PATTERNS),
    ]

    lines = output.splitlines()
    for line in lines:
        for cat, patterns in catalogue:
            for pat in patterns:
                m = pat.search(line)
                if not m:
                    continue
                key = (cat, line.strip()[:120])
                if key in seen:
                    continue
                seen.add(key)
                pkg, registry = extract_pkg_and_registry(line)
                # Extract the error code if pattern looks like YN\d+
                code_match = re.search(r"(YN\d{4}|E[A-Z0-9]+|HTTP \d{3})", line)
                code = code_match.group(1) if code_match else ""
                entry = {
                    "pkg": pkg or "",
                    "registry": registry or "",
                    "code": code,
                    "raw": line.strip()[:300],
                }
                if cat == "patch":
                    entry["noise"] = True
                categories[cat].append(entry)
                break  # First match per line wins; don't double-count

    # Determine primary blocker
    primary = None
    for cat in BLOCKER_PRIORITY:
        if categories[cat]:
            # patch alone is unlikely to be the *primary* blocker; only mark
            # if it's the only thing seen
            if cat == "patch" and any(categories[c] for c in BLOCKER_PRIORITY if c != "patch"):
                continue
            primary = cat
            break

    remediation = REMEDIATION.get(primary, "") if primary else ""
    exit_clue = ""
    if primary == "auth":
        exit_clue = "Other categorised errors after an auth failure are usually follow-on noise."
    elif primary == "network":
        exit_clue = "Other errors may be retry symptoms; fix network first."

    return {
        "categories": categories,
        "primary_blocker": primary,
        "remediation": remediation,
        "exit_clue": exit_clue,
        "total_lines_seen": len(lines),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pkg-manager",
        choices=["yarn", "npm", "pnpm", "bun"],
        default=None,
        help="Hint for which dialect was running (informational)",
    )
    parser.add_argument("file", nargs="?", help="File to read; defaults to stdin")
    args = parser.parse_args()

    if args.file and args.file != "-":
        with open(args.file, encoding="utf-8", errors="replace") as f:
            output = f.read()
    else:
        output = sys.stdin.read()

    result = classify(output)
    if args.pkg_manager:
        result["pkg_manager"] = args.pkg_manager
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
