# Package Upgrade Skill for Claude Code

[繁體中文](README.zh-TW.md) · English

A [Claude Code Skill](https://docs.claude.com/en/docs/claude-code/skills) that automates
package upgrades, CVE remediation, and Jira-driven maintenance work across **Python**,
**JavaScript / TypeScript**, and **Go**. One workflow takes you from trigger →
dependency analysis → breaking-change review → code edits → test verification →
commit / PR / Jira write-back.

---

## 🚀 Quick start

```bash
# Install — macOS / Linux (global, recommended)
bash install.sh
bash install.sh --project          # project-local install (./.claude/skills/)
bash install.sh --skip-permissions # don't write to Claude Code settings.json

# Install — Windows (PowerShell / cmd)
install.bat

# Install — Cygwin64 / Git Bash / MSYS2 (also installs the gh CLI)
bash install-cygwin64.sh
```

```bash
# Verify — macOS / Linux
bash verify_installation.sh

# Verify — Windows (PowerShell / cmd)
verify_installation.bat

# Verify — Cygwin64 / Git Bash / MSYS2
bash verify_installation_cygwin64.sh
```

Two ways to invoke once installed:

**A) One-shot from the shell** — start Claude with the prompt:

```bash
claude "upgrade requests to 2.32.0"
claude "bump axios to 1.7.0"
claude "go get -u github.com/spf13/cobra@v1.8.0"
claude "fix CVE-2024-35195"
claude "V1E-148968"                                          # Jira issue key
claude "https://trendmicro.atlassian.net/browse/V1E-148968"  # Jira URL
```

**B) From inside a Claude Code session** — use the `/package-upgrade` slash command, then describe what you want:

```text
$ claude
> /package-upgrade upgrade requests to 2.32.0
> /package-upgrade fix CVE-2024-35195
> /package-upgrade V1E-148968
```

Or just type the natural-language trigger; the skill description auto-matches phrases like "升級 / bump / update / fix CVE / go get -u":

```text
> upgrade requests to 2.32.0
> can we move django from 4.2 to 5.1?
```

Use the slash form when you want explicit, deterministic invocation (e.g. a phrase Claude might otherwise interpret as a generic question). Use natural language when it's faster to type.

### Install / verify by platform

`install.sh` / `verify_installation.sh` assume a POSIX `$HOME`. On Windows, use the variant that matches how you launch Claude Code — each installer pairs with its own verifier:

| Platform | Install | Verify |
|----------|---------|--------|
| macOS / Linux | `bash install.sh` | `bash verify_installation.sh` |
| Windows (PowerShell / cmd) | `install.bat` | `verify_installation.bat` |
| Windows + Cygwin64 / Git Bash / MSYS2 | `bash install-cygwin64.sh` | `bash verify_installation_cygwin64.sh` |

The Cygwin64 variant installs into `%USERPROFILE%\.claude` (the path Windows-native Claude Code actually reads) rather than Cygwin's `$HOME`, so it must be paired with `verify_installation_cygwin64.sh` — not the plain `verify_installation.sh`.

Full install / manual install / troubleshooting: **[`docs/installation.md`](docs/installation.md)**.

---

## ✨ Features

### Trigger modes

- 📦 **Package + target version** — standard upgrade
- 🔒 **CVE / BDSA / GHSA ID** — advisory lookup (NVD / OSV / GitHub) + risk assessment against actual usage
- 🎫 **Jira URL or issue key** — fetches the ticket, infers the upgrade, comments the report back, prompts a status transition

### Language coverage

| Language | Package managers | Notable extras |
|----------|------------------|----------------|
| Python | `pip`, `poetry`, `uv` | pip-tools, custom `requirements.lock`, no-lock workflows |
| JavaScript / TypeScript | `npm`, `yarn 3` (corepack), `pnpm` (incl. v9 lockfile) | TypeScript `.d.ts` API-surface diff, workspace detection; `bun` planned |
| Go | `go modules` | major version path rewrite (v1 → v2+), `apidiff` surface diff, `govulncheck` reachability, vendor mode, `go.work`, `replace` directives |

Phase 0 language detection order: **Go > JS > Python**.

### Upgrade analysis

- **Dependency analysis** — distinguishes direct / transitive / both; identifies parent-constraint conflicts
- **Transitive lock-only path** — when parents permit it, only the lockfile is touched (declaration files stay clean)
- **Parent-blocked path** — lists every blocking parent + constraint; you decide: upgrade parent / abort / self-pick
- **Dual-track breaking-change analysis** — changelog (PyPI / npm / GitHub Releases / repo CHANGELOG) + git diff (tag-to-tag source diff), cross-referenced
- **Auditable provenance** — reports cite changelog URLs, tag names, commit SHAs, and compare URLs verbatim

### Code edits

- **AST scanning** — parses every import and symbol use, scoped to the actual breaking changes from Phase 3
- **Context-aware patches** — match the project's existing style; presented as unified-diff preview
- **Every code edit requires explicit confirmation**

### Test & diagnose

- **Layered runs** — affected tests first; full suite only after the affected tier is green
- **Three-way diagnosis** — on failure, classifies cause as `SOURCE_CODE` / `TEST_CODE` / `BOTH` / `CONFIG`
- **Test-code edits also require explicit confirmation**
- Capped at **3 fix-loop iterations** to avoid runaway cycles

### Git / PR / Jira integration

- **Mandatory feature branch** — `feature/{ISSUE_KEY}-Update-{pkg}-to-{ver}` (Jira) or `feature/Update-{pkg}-to-{ver}` (normal)
- **Conventional Commits, Jira-aware** — subject `[V1E-148968] type(scope): description`; body contains `Jira: <URL>`
- **Jira link in PR's first line** — title prefixed with `[ISSUE_KEY]`, body opens with `Jira: <URL>`
- **Jira write-back** — posts the migration report; offers a status transition (Done / Resolved / Fixed auto-matched)

### Go-specific safeguards

- **Major version path rewrite** — `v1 → v2+` rewrites import paths across the codebase, not just `go.mod`
- **`govulncheck` reachability** — checks whether the vulnerable symbol is actually called from your code
- **Vendor / workspace aware** — respects `vendor/`, `go.work`, and `replace` directives

### 💌 Feedback companion — `/package-upgrade-feedback`

`install.sh` ships a second skill for sending improvement suggestions back to this repo
(triggered by `/package-upgrade-feedback`, "improve package-upgrade", or
"report package-upgrade issue").

- **LLM-drafted `Improvement.md`** — reads `package-upgrade/SKILL.md` and writes a
  5–10 item improvement draft from an outside-in perspective. Never references your
  environment, target package, CVE / Jira / token, or paths.
- **Sanitizer gate** — free-form input passes through `sanitize_feedback.sh`
  (redacts paths, tokens, Jira keys, emails, private IPs, internal hostnames).
  High-confidence secret patterns (`ghp_*`, `AKIA*`, JWT, private-key blocks) halt the workflow.
- **Review-before-send** — `y` / `edit` / `n`. On `y` the skill runs `gh issue create`
  on `millerlai/auto-package-migration` with label `feedback`. `gh`-unavailable fallback
  prints a pre-filled GitHub Issue URL.

---

## 🔄 The 7-phase pipeline

| Phase | What happens |
|-------|--------------|
| **0. Environment detection** | Language detection (Go > JS > Python) → `detect_env.sh` resolves package manager, version, lockfile mode |
| **1. Input parsing** | Mode A (package + version) / Mode B (CVE / BDSA / GHSA + risk assessment) / Mode C (Jira URL or key via MCP or REST + API token) |
| **2. Dependency analysis** | `dep_tree.*` derives direct / transitive / both; transitive bumps take the lock-only path or trigger a parent-bump prompt |
| **3. Breaking-change analysis** | Changelog + git diff in parallel; source URLs and commit SHAs preserved |
| **4. Code impact analysis** | `ast_scanner.*` locates imports + symbol uses → cross-referenced with Phase 3 → drafts patches |
| **5. Apply the upgrade** | Feature branch → environment snapshot → declaration file + lockfile updated → patches applied |
| **6. Test verification** | Layered runs → three-way diagnosis on failure → up to 3 fix-loop iterations |
| **7. Output & write-back** | Migration report + commit + push + PR; if Jira-triggered → comment + transition prompt |

Full workflow definition: [`package-upgrade/SKILL.md`](package-upgrade/SKILL.md).

---

## 📋 Repository layout

```
auto-package-migration/
├── README.md / README.zh-TW.md     # entry (English / Chinese pointer)
├── CONTRIBUTING.md                  # contributor + developer guide
├── CHANGELOG.md
├── CLAUDE.md                        # repo-level instructions for Claude Code
├── install.sh / install.bat / install-cygwin64.sh
├── verify_installation.sh / verify_installation.bat / verify_installation_cygwin64.sh
├── grant_permissions.py             # writes the allow-list into Claude Code settings
├── pyproject.toml / uv.lock         # this repo's own dev env (UV-managed)
│
├── docs/                            # deeper documentation
│   ├── installation.md              # install / manual / troubleshooting / test projects
│   └── project-status.md            # current maturity + roadmap
│
├── package-upgrade/                 # ⭐ the shipped upgrade skill
│   ├── SKILL.md                     # main skill definition (Phase 0-7)
│   ├── README.md                    # skill-specific overview
│   ├── QUICK_REFERENCE.md           # per-language pkg-manager cheat sheet
│   ├── scripts/                     # helper scripts, organized per language
│   │   ├── common/                  # cross-language: fetch_changelog / save_token / jira_* / parse_pm_errors
│   │   ├── python/                  # detect_env, dep_tree, ast_scanner, run_tests, …
│   │   ├── javascript/              # same shape + runtime_verify + package.json
│   │   └── go/                      # same shape + govulncheck
│   ├── references/                  # lazily loaded by SKILL.md (mirror of scripts/ layout)
│   │   ├── common/                  # auth_tokens / jira_workflow / breaking_change_patterns / …
│   │   ├── python/
│   │   ├── javascript/
│   │   └── go/
│   └── templates/
│
└── package-upgrade-feedback/        # 💌 companion skill — send improvement ideas as GitHub Issues
```

For deeper structure (script-by-script, test fixtures, conventions), see [`CONTRIBUTING.md`](CONTRIBUTING.md).

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

The skill web-searches the advisory, scans the project for use of the affected
functionality, and produces a risk rating (critical / high / medium / low).

### Transitive upgrade

```bash
claude "upgrade urllib3 to 2.2.0"
```

If `urllib3` is pulled in by `requests` rather than declared directly:
- Parent constraint allows it → only the lockfile is updated.
- Parent constraint blocks it → the skill lists every blocker (which parent, which range,
  whether the latest parent unblocks it) and asks how you want to proceed.

### Go major version jump

```bash
claude "upgrade github.com/spf13/viper from v1 to v2"
```

The skill detects the major bump, lists every import path that needs `/v2` appended,
asks for confirmation, then rewrites them along with `go.mod`.

### Jira-triggered

```bash
claude "https://trendmicro.atlassian.net/browse/V1E-148968"
claude "V1E-148968"
```

1. Fetches the ticket (Atlassian MCP if connected, REST + API token fallback otherwise)
2. Extracts target package + version + CVE from summary / description / comments
3. Pauses for you to confirm parse results, then runs Phase 2–7
4. Comments the migration report back to the ticket; offers a status transition

```
Branch:  feature/V1E-148968-Update-requests-to-2.32.0
Commit:  [V1E-148968] chore(deps): upgrade requests to 2.32.0
         …
         Jira: https://trendmicro.atlassian.net/browse/V1E-148968
PR:      Title: [V1E-148968] chore: upgrade requests to 2.32.0
         Body line 1: Jira: https://trendmicro.atlassian.net/browse/V1E-148968
```

### Exploratory query

```bash
claude "can we move django from 4.2 to 5.1?"
```

The full analysis still runs; answer `[N]` at the Phase 4 confirmation gate
to get a feasibility report with zero code changes.

### Feedback about this skill

```bash
claude "/package-upgrade-feedback"
```

Drafts a 10-item improvement proposal (covering only the skill's own design — no data
from your repo), lets you tick which priority groups to act on, sanitizes the body,
shows the final issue text, and on `y` files a GitHub issue with the `feedback` label.

---

## 🔍 Troubleshooting

| Symptom | What to check |
|---------|---------------|
| Skill not found | `ls ~/.claude/skills/package-upgrade/SKILL.md` — re-run `bash install.sh` if missing |
| Permission denied | `find ~/.claude/skills/package-upgrade/scripts \( -name '*.sh' -o -name '*.py' -o -name '*.js' \) -exec chmod +x {} +` |
| Missing deps | `pip install pipdeptree requests`, `brew install jq`; for JS projects: `cd ~/.claude/skills/package-upgrade/scripts/javascript && npm install` |
| `yarn` / `pnpm` not found | corepack-managed binaries are not in PATH — let `detect_env.sh` resolve `pkg_manager_bin`; do not hard-code `yarn` / `pnpm` |
| Jira fetch fails | Check MCP connection state, or fall back to REST + API token (see `docs/installation.md`) |
| `git_diff.sh` cannot find tags | The skill lists available tags so you can pick; non-standard tag naming (e.g. `release-X.Y.Z`) may need manual confirmation |
| `govulncheck` says "not vulnerable" but advisory says CVE applies | Reachability is checked — not all advisories are reachable from your code; see the report's reachability section |

Full troubleshooting + manual install steps: [`docs/installation.md`](docs/installation.md).

---

## 📚 Documentation map

- **You are here** → `README.md`
- **Install / verify / test projects** → [`docs/installation.md`](docs/installation.md)
- **Contribute / develop** → [`CONTRIBUTING.md`](CONTRIBUTING.md)
- **Project status + roadmap** → [`docs/project-status.md`](docs/project-status.md)
- **Release notes** → [`CHANGELOG.md`](CHANGELOG.md)
- **Skill internals** → [`package-upgrade/SKILL.md`](package-upgrade/SKILL.md)
  (full Phase 0–7 workflow definition)
- **Per-language references** → `package-upgrade/references/{common,python,javascript,go}/*.md`
  (lazily loaded by SKILL.md on demand)
- **Repo-level design intent (for Claude Code)** → [`CLAUDE.md`](CLAUDE.md)

---

## 🤝 Contributing

PRs welcome. Suggested directions:

- Additional package managers (conda / pipenv, bun)
- New language tracks (Ruby / Rust / Java) — `scripts/` is now per-language, so adding a new track is mostly self-contained
- Better breaking-change detection patterns
- More test framework support
- Smarter three-way diagnosis
- More issue-tracker integrations (GitHub Issues / GitLab Issues / Linear)

Setup and conventions: [`CONTRIBUTING.md`](CONTRIBUTING.md).

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
- [govulncheck](https://pkg.go.dev/golang.org/x/vuln/cmd/govulncheck) /
  [apidiff](https://pkg.go.dev/golang.org/x/exp/cmd/apidiff) — Go vulnerability + API surface tooling
