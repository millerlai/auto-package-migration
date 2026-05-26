#!/usr/bin/env bash
# sanitize_feedback.sh - Redact sensitive data from feedback markdown.
#
# Usage: bash sanitize_feedback.sh <input.md>
#   - stdout: sanitized markdown
#   - stderr: one line per redaction performed (count + category)
#   - exit 0: clean (sanitized text emitted, even if redactions happened)
#   - exit 5: suspected high-confidence secret/token detected — caller MUST
#             halt the workflow and ask the user to manually verify before sending.
#
# Redaction categories (each replaced with a placeholder):
#   /Users/<name>/..., /home/<name>/..., C:\Users\<name>\...   -> <path>
#   token-shaped strings (gh_*, ghp_*, AKIA*, xoxb-*, JWT, etc.) -> HALT (exit 5)
#   common token-bearing lines (TOKEN=..., api_key=..., password=...) -> <redacted>
#   Jira keys ([A-Z]{2,}-\d+) -> <JIRA-KEY>
#   email addresses -> <email>
#   internal Trend Micro hostnames (*.trendmicro.com) -> <internal-host>
#   private IPv4 ranges (10/8, 172.16/12, 192.168/16) -> <internal-ip>

set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: $0 <input.md>" >&2
    exit 1
fi

INPUT="$1"
if [ ! -f "$INPUT" ]; then
    echo "Input file not found: $INPUT" >&2
    exit 1
fi

# Use a single python pass — easier to reason about regex precedence than
# chained sed expressions, and gives us per-category counts for stderr.
python3 - "$INPUT" <<'PY'
import re
import sys

input_path = sys.argv[1]
with open(input_path, "r", encoding="utf-8") as f:
    text = f.read()

counts = {}

def sub_and_count(pattern, replacement, label, flags=0):
    global text
    regex = re.compile(pattern, flags)
    new_text, n = regex.subn(replacement, text)
    if n > 0:
        counts[label] = counts.get(label, 0) + n
    text = new_text

# --- HIGH-CONFIDENCE SECRETS — halt the workflow ---
# These patterns are specific enough that a positive match almost certainly
# means a real secret leaked into the draft. Detect first, halt before any
# other transformation so we can report exact lines.
HARD_SECRET_PATTERNS = [
    (r"\bghp_[A-Za-z0-9]{36}\b",              "github personal token"),
    (r"\bgho_[A-Za-z0-9]{36}\b",              "github oauth token"),
    (r"\bghs_[A-Za-z0-9]{36}\b",              "github server token"),
    (r"\bghu_[A-Za-z0-9]{36}\b",              "github user token"),
    (r"\bgithub_pat_[A-Za-z0-9_]{82}\b",      "github fine-grained PAT"),
    (r"\bAKIA[0-9A-Z]{16}\b",                 "aws access key id"),
    (r"\bASIA[0-9A-Z]{16}\b",                 "aws temp access key id"),
    (r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b",     "slack token"),
    (r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\b", "jwt"),
    (r"\bAIza[0-9A-Za-z_-]{35}\b",            "google api key"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----",   "private key block"),
]
hard_hits = []
for pattern, label in HARD_SECRET_PATTERNS:
    for m in re.finditer(pattern, text):
        line_no = text[:m.start()].count("\n") + 1
        hard_hits.append((line_no, label, m.group(0)[:8] + "..."))

if hard_hits:
    print("HALT: suspected secret/token detected in feedback draft.", file=sys.stderr)
    print("      Do NOT submit until the user verifies these are not real credentials.", file=sys.stderr)
    for line_no, label, snippet in hard_hits:
        print(f"      line {line_no}: {label} (starts with {snippet})", file=sys.stderr)
    sys.exit(5)

# --- LOWER-CONFIDENCE TOKEN-BEARING LINES ---
# Lines of the form KEY=VALUE or "key": "value" where KEY suggests a secret.
# Replace the value portion only — keep the variable name so the feedback
# still makes sense ("we set TOKEN=<redacted> but ...").
sub_and_count(
    r"(?im)^([ \t]*(?:export[ \t]+)?(?:[A-Z][A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API[_-]?KEY|PRIVATE[_-]?KEY|AUTH|CREDENTIAL)[A-Z0-9_]*)[ \t]*=[ \t]*).+$",
    r"\1<redacted>",
    "token-bearing env line",
)
sub_and_count(
    r'(?i)("(?:token|secret|password|api[_-]?key|auth)"[ \t]*:[ \t]*")[^"]+(")',
    r"\1<redacted>\2",
    "token-bearing json field",
)

# --- ABSOLUTE PATHS ---
# Match the home-prefix segment and the next path component (the username),
# then replace the *entire absolute path* up to the next whitespace/quote/
# bracket so the rest of the path doesn't leak project layout either.
sub_and_count(
    r"/Users/[^/\s'\"`)\]]+(?:/[^\s'\"`)\]]*)?",
    "<path>",
    "absolute path (macOS)",
)
sub_and_count(
    r"/home/[^/\s'\"`)\]]+(?:/[^\s'\"`)\]]*)?",
    "<path>",
    "absolute path (linux)",
)
sub_and_count(
    r"[A-Z]:\\Users\\[^\\s'\"`)\]]+(?:\\[^\s'\"`)\]]*)?",
    "<path>",
    "absolute path (windows)",
)

# --- JIRA KEYS ---
# Form like ABC-1234 or V1E-148968. Prefix starts with an uppercase letter
# and may contain digits (real example: V1E). Length 2-6 chars to avoid
# matching things like "HTTP-2" being treated the same as "ABCDEFG-1".
sub_and_count(
    r"\b[A-Z][A-Z0-9]{1,5}-\d{2,7}\b",
    "<JIRA-KEY>",
    "jira issue key",
)

# --- EMAIL ADDRESSES ---
sub_and_count(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    "<email>",
    "email",
)

# --- INTERNAL HOSTNAMES ---
sub_and_count(
    r"\b[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.trendmicro\.com\b",
    "<internal-host>",
    "trendmicro hostname",
)

# --- PRIVATE IPv4 RANGES ---
sub_and_count(
    r"\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
    "<internal-ip>",
    "private ip (10/8)",
)
sub_and_count(
    r"\b172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b",
    "<internal-ip>",
    "private ip (172.16/12)",
)
sub_and_count(
    r"\b192\.168\.\d{1,3}\.\d{1,3}\b",
    "<internal-ip>",
    "private ip (192.168/16)",
)

sys.stdout.write(text)

if counts:
    print("Sanitization report:", file=sys.stderr)
    for label, n in counts.items():
        print(f"  - {label}: {n}", file=sys.stderr)
else:
    print("Sanitization report: no redactions needed.", file=sys.stderr)
PY
