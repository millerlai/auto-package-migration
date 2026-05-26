# Package Upgrade Skill for Claude Code

[繁體中文](README.zh-TW.md) · English

A [Claude Code Skill](https://docs.claude.com/en/docs/claude-code/skills) that automates package upgrades, CVE remediation, and Jira-driven maintenance work across **Python**, **JavaScript / TypeScript**, and **Go**. One workflow takes you from trigger → dependency analysis → breaking-change review → code edits → test verification → commit / PR / Jira write-back.

---

## 🚀 Quick start

### Install

```bash
# Global install (recommended — available to all projects)
bash install.sh

# Or project-local install
bash install.sh --project
```

Windows users can run `install.bat` (PowerShell) or `install-cygwin64.sh` (Cygwin).

### Verify

```bash
bash verify_installation.sh
```

### Trigger

Any of the following will trigger the skill:

```bash
claude "upgrade requests to 2.32.0"
claude "bump axios to 1.7.0"
claude "go get -u github.com/spf13/cobra@v1.8.0"
claude "fix CVE-2024-35195"
claude "https://trendmicro.atlassian.net/browse/V1E-148968"
claude "V1E-148968"
claude "can we move django from 4.2 to 5.1?"
```

---

## ✨ Features

### Trigger modes
- 📦 **Package name + target version** — standard upgrade
- 🔒 **CVE / BDSA / GHSA ID** — looks up advisory metadata (NVD / OSV / GitHub), assesses risk against actual usage in your code
- 🎫 **Jira URL or issue key** — fetches the ticket, infers what to upgrade, comments the final report back, and (with your approval) transitions the status

### Language coverage
| Language | Package managers | Notable extras |
|----------|------------------|----------------|
| Python | `pip`, `poetry`, `uv` | pip-tools (`requirements.in` / `requirements.txt`), custom `requirements.lock`, no-lock workflow |
| JavaScript / TypeScript | `npm`, `yarn 3` (corepack) | TypeScript `.d.ts` API-surface diff; `pnpm` / `bun` planned |
| Go | `go modules` | major version path rewrite (v1 → v2+), `apidiff` API-surface diff, `govulncheck` reachability, vendor mode, `go.work` workspaces, `replace` directives |

Language detection order (Phase 0): **Go > JS > Python**.

### Upgrade analysis
- 🌳 **Dependency analysis** — distinguishes direct / transitive / both; identifies parent-constraint conflicts
- 🪶 **Transitive lock-only path** — when a transitive bump is allowed by parents, **only the lockfile is touched** (declaration files stay clean)
- 🔁 **Parent-blocked path** — lists every blocking parent with its constraint range; lets you choose to upgrade the parent, abort, or self-pick
- 🔬 **Dual-track breaking-change analysis** — reads the changelog (PyPI / npm / GitHub Releases / repo `CHANGELOG`) and the git diff (tag-to-tag source diff) in parallel, cross-references both
- 📚 **Auditable provenance** — reports cite changelog URLs, old/new tags, old/new commit SHAs, and compare URLs verbatim so reviewers can verify

### Code edits
- 🌲 **AST scanning** — parses all imports and symbol uses in the project, scoped to the actual breaking changes from Phase 3
- 🧠 **Context-aware patches** — generated against the project's own style, presented as unified-diff previews
- ✅ **Every code edit requires your explicit confirmation**

### Test & diagnose
- 🎯 **Layered test runs** — affected tests first; full suite only after the affected tier is green
- 🔍 **Three-way diagnosis** — on failure, the skill reads traceback + test code + business code + breaking-change list, and classifies the cause as `SOURCE_CODE` / `TEST_CODE` / `BOTH` / `CONFIG`
- 🤝 **Test-code edits also require explicit confirmation**
- 🔁 Capped at **3 fix-loop iterations** to avoid runaway cycles

### Git / PR / Jira integration
- 🌿 **Mandatory feature branch** — `feature/{ISSUE_KEY}-Update-{pkg}-to-{ver}` (Jira-triggered) or `feature/Update-{pkg}-to-{ver}` (normal)
- 📝 **Conventional Commits, Jira-aware** — subject `[V1E-148968] type(scope): description`, body contains `Jira: <full URL>`
- 🔗 **Jira link in the first line of the PR** — title prefixed with `[ISSUE_KEY]`, body opens with `Jira: <url>` so reviewers see it on the PR list card
- 💬 **Jira write-back** — posts the migration report as a comment when the upgrade is done, then offers a status transition (Done / Resolved / Fixed and synonyms are auto-matched)

### Go-specific safeguards
- ⚠️ **Major version path rewrite** — when going from `v1` to `v2+`, the skill rewrites import paths (`example.com/foo` → `example.com/foo/v2`) across the codebase, not just `go.mod`
- 🛡️ **govulncheck reachability** — when fixing a Go CVE, the skill checks whether the vulnerable symbol is actually called from your code
- 📦 **Vendor / workspace aware** — respects `vendor/`, `go.work`, and `replace` directives instead of stomping on them

### 💌 Feedback companion — `/package-upgrade-feedback`

`install.sh` ships a second skill for sending improvement suggestions back to this repo. Triggered by `/package-upgrade-feedback`, "improve package-upgrade", or "report package-upgrade issue".

- 🧠 **LLM-drafted `Improvement.md`** — reads the installed `package-upgrade/SKILL.md` and writes a 5–10 item improvement draft from an outside-in perspective. The draft **never references** your environment, target package, CVE / Jira / token, file paths, or any other private data.
- ☑️ **Multi-select + free-form input** — uses `AskUserQuestion`: tick which priority groups you care about, optionally add free-form context via the auto-supplied Other field.
- 🛡️ **Sanitizer gate** — free-form input passes through `sanitize_feedback.sh` (redacts paths, tokens, Jira keys, emails, private IPs, internal hostnames). High-confidence secret patterns (`ghp_*`, `AKIA*`, JWT, private-key blocks, …) halt the workflow.
- 👀 **Review-before-send** — `y` / `edit` / `n`. On `y` the skill immediately runs `gh issue create` on `millerlai/auto-package-migration` with label `feedback`; no second confirmation.
- 🔁 **`gh`-unavailable fallback** — prints a pre-filled GitHub Issue URL you can paste into the browser.

---

## 🔄 The 7-phase pipeline

| Phase | What happens |
|-------|--------------|
| **0. Environment detection** | Language detection (Go > JS > Python) → `detect_env*.{sh}` picks the package manager, version, and lockfile mode |
| **1. Input parsing** | Mode A (package name) / Mode B (CVE / BDSA / GHSA, with web search + risk assessment) / Mode C (Jira URL or key — fetched via MCP or REST + API token) |
| **2. Dependency analysis** | `dep_tree*` derives `direct` / `transitive` / `both`; transitive bumps take the lock-only path or trigger a parent-bump prompt |
| **3. Breaking-change analysis** | Changelog + git diff in parallel; source URLs and commit SHAs are preserved for citation |
| **4. Code impact analysis** | `ast_scanner*` locates imports and symbol uses → cross-referenced with Phase 3 to draft patches |
| **5. Apply the upgrade** | Feature branch → environment snapshot → declaration file + lockfile updated (or lock-only) → code patches applied |
| **6. Test verification** | Layered runs → three-way diagnosis on failure → up to 3 fix-loop iterations |
| **7. Output & write-back** | Migration report + commit + push + PR; if Jira-triggered → comment + transition prompt |

Full workflow definition: [`package-upgrade/SKILL.md`](package-upgrade/SKILL.md).

---

## 📋 Repository layout

```
auto-package-migration/
├── README.md                          # this file
├── README.zh-TW.md                    # Traditional Chinese README
├── GETTING_STARTED.md                 # 3-minute walkthrough
├── INSTALLATION_GUIDE.md              # detailed install guide
├── VERIFICATION_CHECKLIST.md          # post-install checks
├── DEVELOPMENT.md                     # dev guide (UV-based)
├── CONTRIBUTING.md                    # contribution guide
├── CHANGELOG.md
├── CLAUDE.md                          # repo-level instructions for Claude Code
├── install.sh                         # POSIX installer
├── install.bat                        # Windows installer
├── install-cygwin64.sh                # Cygwin installer (bundles gh CLI)
├── verify_installation.sh
├── grant_permissions.py               # writes the allow-list into Claude Code settings
├── pyproject.toml / uv.lock           # this repo's own dev env (UV-managed)
│
├── package-upgrade/                   # ⭐ the shipped upgrade skill (copied to ~/.claude/skills/)
│   ├── SKILL.md                       # main skill definition (Phase 0–7)
│   ├── README.md                      # end-user usage doc
│   ├── QUICK_REFERENCE.md
│   ├── LICENSE                        # MIT
│   ├── scripts/                       # helper scripts — three parallel tracks
│   │   ├── detect_env.sh              # py / js / go variants for every script
│   │   ├── detect_env_js.sh
│   │   ├── detect_env_go.sh
│   │   ├── dep_tree.py
│   │   ├── dep_tree_js.js
│   │   ├── dep_tree_go.{sh,py}
│   │   ├── ast_scanner.py
│   │   ├── ast_scanner_js.js
│   │   ├── ast_scanner_go.go
│   │   ├── api_surface_diff_js.js     # TypeScript .d.ts surface diff
│   │   ├── api_surface_diff_go.sh     # Go apidiff
│   │   ├── govulncheck_go.sh
│   │   ├── git_diff.sh / git_diff_js.sh / git_diff_go.sh
│   │   ├── fetch_changelog.py
│   │   ├── preflight.sh / preflight_go.sh
│   │   ├── snapshot_env*.sh
│   │   ├── run_tests*.sh
│   │   ├── validate_lockfile.sh / validate_modfile_go.sh
│   │   ├── parse_pm_errors.py
│   │   ├── save_token.sh              # writes auth tokens with chmod 600 + .gitignore
│   │   ├── jira_fetch.py / jira_comment.py / jira_transition.py
│   │   └── package.json               # inner package.json for JS helpers
│   ├── references/                    # lazily loaded by SKILL.md
│   │   ├── pip_workflow.md / poetry_workflow.md / uv_workflow.md
│   │   ├── npm_workflow.md / yarn_workflow.md / js_workflow.md
│   │   ├── js_ast_strategy.md
│   │   ├── go_workflow.md
│   │   ├── go_major_version_paths.md
│   │   ├── go_replace_semantics.md
│   │   ├── govulncheck.md
│   │   ├── breaking_change_patterns{,_js,_go}.md
│   │   ├── IMPORTANT_DEPENDENCY_UPDATE.md
│   │   ├── PIP_LOCK_PATTERNS.md
│   │   ├── auth_tokens.md
│   │   ├── bdsa_mapping.md
│   │   └── jira_workflow.md
│   └── templates/
│       └── report_structure.md        # report-writing template
│
├── package-upgrade-feedback/          # 💌 companion skill — send improvement ideas back as GitHub Issues
│   ├── SKILL.md                       # 5-phase flow: LLM draft → ask → sanitize → review → send
│   └── scripts/
│       ├── sanitize_feedback.sh       # redacts paths / tokens / Jira keys / emails / private IPs
│       └── submit_feedback.sh         # `gh issue create` wrapper with non-gh URL fallback
│
└── package-upgrade-agent-architecture.md  # full architecture doc
```

---

## 📖 Examples

### Standard upgrade

```bash
claude "upgrade requests to 2.32.0"
claude "bump axios to 1.7.0"
claude "go get -u github.com/spf13/cobra@v1.8.0"
```

### CVE remediation

```bash
claude "fix CVE-2024-35195"
```

The skill web-searches the advisory, scans the project for use of the affected functionality, and produces a risk rating (critical / high / medium / low).

### Transitive upgrade

```bash
claude "upgrade urllib3 to 2.2.0"
```

If `urllib3` is pulled in by `requests` rather than declared directly:
- Parent constraint allows it → only the lockfile is updated (`poetry.lock` / `uv.lock` / `requirements.lock` / `package-lock.json` / `yarn.lock` / `go.sum`); the declaration file is untouched.
- Parent constraint blocks it → the skill lists every blocker (which parent, which range, whether the latest parent unblocks it) and asks how you want to proceed.

### Go major version jump

```bash
claude "upgrade github.com/spf13/viper from v1 to v2"
```

The skill detects the major bump, lists every import path that needs `/v2` appended, asks for confirmation, then rewrites them along with `go.mod`.

### Jira-triggered

```bash
claude "https://trendmicro.atlassian.net/browse/V1E-148968"
# or just the issue key
claude "V1E-148968"
```

What happens:
1. Fetches the ticket (Atlassian MCP if connected, REST + API token fallback otherwise)
2. Extracts the target package + version + CVE from summary / description / comments
3. Pauses for you to confirm what it parsed, then runs Phase 2–7
4. Comments the migration report back to the ticket and offers a status transition

Resulting git artifacts:
```
Branch:  feature/V1E-148968-Update-requests-to-2.32.0
Commit:  [V1E-148968] chore(deps): upgrade requests to 2.32.0
         <body>
         Jira: https://trendmicro.atlassian.net/browse/V1E-148968
PR:      Title: [V1E-148968] chore: upgrade requests to 2.32.0
         Body line 1: Jira: https://trendmicro.atlassian.net/browse/V1E-148968
```

### Exploratory query

```bash
claude "can we move django from 4.2 to 5.1?"
```

The full analysis still runs, but you can answer `[N]` at the Phase 4 confirmation gate — you get a feasibility report without any code being touched.

### Sending feedback about this skill

```bash
claude "/package-upgrade-feedback"
```

The companion skill drafts a 10-item improvement proposal (covering only the skill's own design — no data from your current repo), lets you tick which priority groups to act on and add free-form context, sanitizes the combined body, shows you the final issue text, and on `y` runs `gh issue create` to file an issue on `millerlai/auto-package-migration` with the `feedback` label.

---

## 🔧 Manual install

If you'd rather skip `install.sh`:

```bash
# 1. Copy the skill
cp -r package-upgrade ~/.claude/skills/

# 2. Make helpers executable
chmod +x ~/.claude/skills/package-upgrade/scripts/*.sh
chmod +x ~/.claude/skills/package-upgrade/scripts/*.py

# 3. Python deps
pip install pipdeptree requests

# 4. JS helper deps (only needed for JS/TS projects)
cd ~/.claude/skills/package-upgrade/scripts && npm install && cd -

# 5. System tools
brew install jq          # macOS
sudo apt-get install jq  # Debian / Ubuntu

# 6. (Optional) GitHub CLI for auto-PR
brew install gh

# 7. (Optional, Go projects) govulncheck + apidiff
go install golang.org/x/vuln/cmd/govulncheck@latest
go install golang.org/x/exp/cmd/apidiff@latest

# 8. Verify
bash verify_installation.sh
```

### Atlassian integration (optional — enables Jira triggers)

Pick one:

**Option A — Atlassian MCP.** Connect Atlassian via the [Claude connector page](https://claude.ai/settings/connectors); browser login is enough, no local tokens.

**Option B — REST + API token.** No MCP required; provide ad-hoc per session:
```bash
export ATLASSIAN_EMAIL="you@example.com"
export ATLASSIAN_API_TOKEN="<token>"
# Token: https://id.atlassian.com/manage-profile/security/api-tokens
```
The skill auto-detects MCP availability and falls back to `scripts/jira_*.py`. The token only lives in the shell session — it is never written to disk by the skill.

---

## 🔍 Troubleshooting

| Symptom | What to check |
|---------|---------------|
| Skill not found | `ls ~/.claude/skills/package-upgrade/SKILL.md` — re-run `bash install.sh` if missing |
| Permission denied | `chmod +x ~/.claude/skills/package-upgrade/scripts/*.{sh,py}` |
| Missing deps | `pip install pipdeptree requests`, `brew install jq`, plus `npm install` inside `scripts/` for JS projects |
| `yarn` not found | corepack-managed yarn is not in PATH — let `detect_env_js.sh` resolve `pkg_manager_bin`; do not hard-code `yarn` |
| Jira fetch fails | Check MCP connection state, or fall back to REST + API token |
| `git_diff*.sh` cannot find tags | The skill lists available tags so you can pick; non-standard tag naming (e.g. `release-X.Y.Z`) may need manual confirmation |
| `govulncheck` says "not vulnerable" but advisory says CVE applies | Reachability is checked — not all advisories are reachable from your code. Check the report's reachability section. |

See `INSTALLATION_GUIDE.md` for the long form.

---

## 🛠️ Development

This repo uses **UV** for its own dev environment. Helper scripts under `package-upgrade/scripts/` run via `uv run` during development.

```bash
git clone https://github.com/millerlai/auto-package-migration.git
cd auto-package-migration

# Install UV
curl -LsSf https://astral.sh/uv/install.sh | sh

# Sync deps (creates .venv/, installs editable project)
uv sync

# Run a helper
uv run python package-upgrade/scripts/dep_tree.py . requests
uv run python package-upgrade/scripts/ast_scanner.py . requests

# Format / lint / type-check
uv run black package-upgrade/scripts/
uv run ruff check --fix package-upgrade/scripts/
uv run mypy package-upgrade/scripts/*.py

# Tests
uv run pytest
uv run pytest --cov=package-upgrade --cov-report=html
```

JS helpers have their own `package.json` at `package-upgrade/scripts/package.json` — `install.sh` runs `npm install` inside that directory. `scripts/node_modules/` is gitignored.

More detail in `DEVELOPMENT.md` and `package-upgrade-agent-architecture.md`.

---

## 🤝 Contributing

PRs welcome. Suggested directions:
- Additional package managers (conda / pipenv, pnpm / bun)
- New language tracks (Ruby / Rust / Java)
- Better breaking-change detection patterns
- More test framework support
- Smarter three-way diagnosis
- More issue-tracker integrations (GitHub Issues / GitLab Issues / Linear)

See `CONTRIBUTING.md`.

---

## 📄 License

MIT — see `package-upgrade/LICENSE`.

---

## 🙏 Acknowledgements

- [Claude Code](https://claude.ai/code) by Anthropic
- [Atlassian Rovo MCP](https://www.atlassian.com/) — Jira / Confluence integration
- [pipdeptree](https://github.com/tox-dev/pipdeptree) — Python dependency tree
- [poetry](https://python-poetry.org/) / [uv](https://github.com/astral-sh/uv) — Python package managers
- [corepack](https://nodejs.org/api/corepack.html) — yarn 3 / pnpm shim
- [govulncheck](https://pkg.go.dev/golang.org/x/vuln/cmd/govulncheck) / [apidiff](https://pkg.go.dev/golang.org/x/exp/cmd/apidiff) — Go vulnerability and API surface tooling
