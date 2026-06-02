# Improvement Tasks — Staff Engineer Review (2026-06)

Prioritised, actionable backlog from the full-repo review. Each task lists the
evidence (`file:line`), the fix, and a verification step. Checkboxes track progress.

Theme: **the safety-critical and most-recently-added surfaces (token handling,
provenance hook, sanitizer) are the least guarded.** P1 work concentrates there.

---

## P1 — Fix before next release

### [ ] T1. Feedback sanitizer misses JFROG / Atlassian / Bearer tokens
- **Evidence:** `package-upgrade-feedback/scripts/sanitize_feedback.sh:57-69` HARD patterns cover only `ghp_`/AWS/Slack/JWT/Google/PEM. JFROG_TOKEN / ATLASSIAN_API_TOKEN are opaque (no prefix) → unredacted; bare token in prose and `Bearer <x>` also pass.
- **Fix:** add high-entropy detector (base64/hex ≥ 32 chars → HALT), `Bearer\s+\S+`, `Authorization:` line redaction. HALT-on-uncertainty (public-issue path).
- **Verify:** `tests/test_sanitize_feedback.py` — JFROG/Atlassian/Bearer/high-entropy samples HALT or redact.

### [ ] T2. Token value shell-evaluated when preflight sources `.env.*` (local RCE)
- **Evidence:** `scripts/common/save_token.sh:98,133` writes `KEY=$VALUE` unquoted; `scripts/{python,javascript,go}/preflight*.sh` load via `set -a; . "$tok_file"`. `$(...)` in value executes.
- **Fix:** single-quote value on write + reject shell metachars; preflight reads `KEY=VALUE` line-by-line instead of `source`.
- **Verify:** `tests/test_save_token.py` — value with `$(...)` stored literally, no execution on read-back.

### [ ] T3. `git clone` on attacker-controlled repo URL, no transport allowlist (local RCE)
- **Evidence:** `scripts/common/git_diff.sh:20`, `scripts/javascript/git_diff.sh`, `scripts/go/git_diff.sh` run `git clone "$REPO_URL"`; URL from registry metadata. `ext::` transport = RCE.
- **Fix:** validate `^https://` before clone; pass `-c protocol.ext.allow=never -c protocol.file.allow=never` / `GIT_ALLOW_PROTOCOL=https`.
- **Verify:** `ext::`/`file://` URL rejected; https still works.

### [ ] T4. JS helpers interpolate pkg/version into `execSync` (shell injection)
- **Evidence:** `scripts/javascript/api_surface_diff.js:64` (`npm pack ${pkg}@${version}`), `scripts/javascript/dep_tree.js:716` (`npm view ${parentName}@latest`).
- **Fix:** convert to `execFileSync('npm', [...])` (no shell). Also `npm ls` / `tar` calls for consistency.
- **Verify:** node syntax check + existing `test_dep_tree_js.py` / `test_api_surface_diff_js.py` stay green.

### [ ] T5. No tests for newest safety-critical code
- **Evidence:** `save_token.sh`, `provenance_stop_hook.py`, `verify_provenance.sh`, `grant_permissions.py:138-159` (Stop-hook merge) have no behaviour tests; CI `--yes` forces `SKIP_PERMISSIONS=true` so settings→hook path never exercised.
- **Fix:** add `test_save_token.py`, `test_provenance_stop_hook.py`, hook-merge tests in `test_grant_permissions.py`; CI step running `grant_permissions.py --settings <tmp>` asserting hook added + idempotent.
- **Verify:** `uv run pytest` green; new tests fail if reverted.

### [ ] T6. References use obsolete flat script paths in runnable blocks
- **Evidence:** `references/javascript/ast_strategy.md:21,86,108,143`; `references/go/govulncheck.md:129,153`; `references/common/auth_tokens.md:68,88,105`; `references/common/jira_workflow.md:79,187-188`; `references/go/workflow.md:51-58`.
- **Fix:** rewrite fenced command blocks to `scripts/<lang>/<name>` (+ `scripts/common/...`). Align CLAUDE.md fan-out section.
- **Verify:** grep references for `scripts/[a-z_]*_\(js\|go\)\.` finds no runnable command paths.

---

## P2 — Schedule in

### [ ] T7. `recommended_strategy` schema divergence (JS returns null / empty)
- **Evidence:** `scripts/javascript/dep_tree.js:1135` → `null`; `python/dep_tree.py:884-892` & `go/dep_tree.py` guarantee terminal `{"type":"unknown"}`.
- **Fix:** append `unknown` fallback strategy in JS so `recommended_strategy` is always a string and array non-empty.
- **Verify:** `test_dep_tree_js.py` — orphan transitive yields `unknown`, not null.

### [ ] T8. `detect_env_go.sh` can emit invalid JSON for vendor count
- **Evidence:** `scripts/go/detect_env.sh:102` — `grep -c ... || echo 0` yields `0\n0` when file exists but no matches.
- **Fix:** `$( { grep -c '^# ' f 2>/dev/null || true; } | head -1 )` and default empty → 0.
- **Verify:** `test_detect_env_go.py` — empty vendor/modules.txt → valid JSON, count 0.

### [ ] T9. provenance validator can false-block legitimate 0-breaking-change upgrades
- **Evidence:** `scripts/common/verify_provenance.sh:67-72` requires `confidence`/api-surface note; `templates/report_structure.md` lacks that section.
- **Fix:** add "API Surface Diff 來源 (confidence_score)" section to template (and/or accept explicit "0 breaking changes, three tracks verified").
- **Verify:** a 0-BC report following the template passes `verify_provenance.sh` (exit 0).

### [ ] T10. Jira REST scripts: no host allowlist (SSRF + token to arbitrary host)
- **Evidence:** `scripts/common/jira_fetch.py:35`, `jira_comment.py:60`, `jira_transition.py:52,72` build `https://{site}/...` from argv with Basic auth.
- **Fix:** validate `site` against `*.atlassian.net` + known GHE hosts / strict hostname regex before attaching creds.
- **Verify:** test rejects `site` like `evil.com` / with path/scheme injected.

### [ ] T11. CI doesn't run mypy; pyproject URLs are placeholders
- **Evidence:** `.github/workflows/ci.yml:29-33` (ruff+black only); `pyproject.toml:39-42` `YOUR_USERNAME`.
- **Fix:** add mypy step; replace `YOUR_USERNAME` → `millerlai`.
- **Verify:** CI config contains mypy; `grep YOUR_USERNAME` empty.

### [ ] T12. Installers use bare `pip install` (PEP 668 failure)
- **Evidence:** `install.sh:174`, `install.bat:181`, `install-cygwin64.sh:233`.
- **Fix:** detect venv / fall back to `--user` / print actionable guidance.
- **Verify:** manual read-through; consistent across three installers.

---

## P3 — Cleanup

### [ ] T13. Sanitizer Windows-path regex malformed class
- **Evidence:** `sanitize_feedback.sh:113` `[^\\s...]` treats `\s` as literal `\`+`s`.
- **Fix:** use `[^\s'"`)\]]` like macOS/linux siblings. (Folded into T1.)

### [ ] T14. Dead code `parse_require_line` in Go dep_tree
- **Evidence:** `scripts/go/dep_tree.py:206-210` — contradicts own type hint, never called.
- **Fix:** remove.

### [ ] T15. Orphan reference + uncalled helper
- **Evidence:** `references/python/pip_lock_patterns.md` never lazy-loaded; `scripts/common/parse_pm_errors.py` described in yarn/pnpm refs but no phase calls it.
- **Fix:** wire pointers from SKILL.md or delete; decide single source of truth.

### [ ] T16. Dead link in report template
- **Evidence:** `templates/report_structure.md:379` → non-existent `package-upgrade-agent-architecture.md`.
- **Fix:** remove line / inline short example.

### [ ] T17. Truncated sentence in SKILL.md Phase 2.1
- **Evidence:** `SKILL.md:753-756` sentence ends with no predicate.
- **Fix:** complete to mirror JS/Go wording.
