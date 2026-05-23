# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

This repo is **not** an application — it is the source for a **Claude Code Skill** called `package-upgrade`. The shipped artifact is the `package-upgrade/` directory, which gets copied into `~/.claude/skills/` (or `./.claude/skills/`) by `install.sh`. Everything else in the repo root (`install.sh`, `verify_installation.sh`, `pyproject.toml`, docs) is tooling around packaging, installing, and developing that skill.

The skill itself drives Claude through a 7-phase package-upgrade / CVE-fix workflow across **Python (pip / poetry / uv)**, **JavaScript / TypeScript (npm / yarn3)**, and **Go (modules)**. The skill instructions live in `package-upgrade/SKILL.md`; Claude is the orchestrator and reasoning engine, helper scripts only produce structured data.

## Working principles

Behavioral guidelines that bias toward caution over speed. For trivial tasks (typo fixes, one-line tweaks), use judgment.

### 1. Think before coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

Common trap in this repo: a request like "add support for X" might mean a new helper script, a new `references/*.md`, a new `SKILL.md` phase, or all three. Confirm scope before writing code.

### 2. Simplicity first

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask: "Would a senior engineer say this is overcomplicated?" If yes, simplify. The skill scripts deliberately stay procedural — resist adding class hierarchies or plugin systems unless an existing pattern already uses one.

### 3. Surgical changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.

When your changes create orphans:
- Remove imports / variables / functions that **your** changes made unused.
- Don't remove pre-existing dead code unless asked.

Repo-specific edge: the three language variants (`*.py` / `*_js.js` / `*_go.sh`) are deliberately parallel. Touching one because you're "in the area" is **not** justification for touching the others — only sync them when the user's request actually requires it. The same applies to `SKILL.md` ↔ `references/*.md`: edit the file the change belongs in, not every file that mentions the topic.

The test: every changed line should trace directly to the user's request.

### 4. Goal-driven execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass."
- "Fix the bug" → "Write a test that reproduces it, then make it pass."
- "Refactor X" → "Ensure tests pass before and after."
- "Update a helper script" → "Update both the script and the `SKILL.md` phase that calls it; re-read both to verify they describe the same CLI and output schema."

For multi-step tasks, state a brief plan:

```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

## Common commands

This project uses **UV** for its own dev environment. The helper scripts under `package-upgrade/scripts/` are run via `uv run` during development.

```bash
# Initial setup (creates .venv/, installs deps + editable project)
uv sync

# Run a helper script during development
uv run python package-upgrade/scripts/dep_tree.py . requests
uv run python package-upgrade/scripts/ast_scanner.py . requests

# Format / lint / type-check (settings in pyproject.toml: black line-length=100, ruff target=py38)
uv run black package-upgrade/scripts/
uv run ruff check package-upgrade/scripts/
uv run ruff check --fix package-upgrade/scripts/
uv run mypy package-upgrade/scripts/*.py

# Tests (no tests exist yet — pytest config in pyproject.toml expects tests/)
uv run pytest
uv run pytest tests/test_dep_tree.py        # single file
uv run pytest --cov=package-upgrade --cov-report=html

# Install / verify the skill itself
bash install.sh                # global → ~/.claude/skills/package-upgrade
bash install.sh --project      # project-local → ./.claude/skills/package-upgrade
bash install.sh --skip-permissions   # skip writing to Claude Code settings.json
bash verify_installation.sh
```

The JS helpers (`scripts/dep_tree_js.js`, `scripts/api_surface_diff_js.js`, etc.) have their **own** `package.json` at `package-upgrade/scripts/package.json` — `install.sh` runs `npm install` inside that directory. `package-upgrade/scripts/node_modules/` is gitignored.

## Architecture you need before editing

### The repo is the skill source, not the skill

Two things to keep straight:

1. **`package-upgrade/`** — the publishable skill. Edits here change what end-users get after running `install.sh`. The skill is self-contained: `SKILL.md` (instructions) + `scripts/` (helpers) + `references/` (per-tool how-tos that `SKILL.md` lazily loads) + `templates/`.
2. **Repo root** — installer (`install.sh`), permissions writer (`grant_permissions.py`), verifier (`verify_installation.sh`), and developer docs. These are not shipped to end-users.

Changes to skill behavior almost always touch both `SKILL.md` (the phase that uses the script) **and** the script itself. The two must stay in sync — `SKILL.md` documents the script's CLI and output schema.

### Helper scripts are deterministic; Claude is the LLM

There is no external LLM call inside any helper. Scripts produce structured JSON; `SKILL.md` tells Claude to read that JSON, reason over it, and call the next script. When adding a new analysis step:

- Put deterministic work (parse a lockfile, walk an AST, fetch a URL) in a script that prints JSON to stdout, errors to stderr.
- Put judgment work (decide breaking-change severity, write a patch, compose a PR) in `SKILL.md` as instructions Claude follows.

### Language fan-out — three parallel tracks, same shape

Every script that does language-specific work exists in three variants by suffix:

```
detect_env.sh            dep_tree.py        ast_scanner.py        run_tests.sh        # Python
detect_env_js.sh         dep_tree_js.js     ast_scanner_js.js     run_tests_js.sh     # JS/TS
detect_env_go.sh         dep_tree_go.sh     ast_scanner_go.go     run_tests_go.sh     # Go
```

Phase 0 of `SKILL.md` picks the language (detection order: **Go > JS > Python**), then every subsequent phase calls the matching variant. The output schemas across the three are **intentionally aligned** where possible (e.g. `dep_tree*` all return `dependency_type`, `current_version`, `parent_packages`, `version_constraints`), with language-specific extensions (Go adds `is_major_version_jump`, JS adds `is_peer` and `declared_in`, etc.). If you add a field to one, consider whether the others need it.

### The Phase pipeline

`SKILL.md` is organized into Phase 0 → Phase 7, each gated by user confirmations. Cross-cutting concepts:

- **Phase 0** does environment detection + pre-flight checks (`preflight.sh` / `preflight_go.sh`). Pre-flight surfaces blockers (missing auth tokens, dirty working tree, wrong tool versions) **before** any work starts. Auth tokens go through `save_token.sh`, which handles `chmod 600` and `.gitignore` — **never** write `.env.*` files directly with Write/Edit.
- **Phase 1** has three trigger modes: A=package name, B=CVE/BDSA/GHSA, C=Jira URL/key. Mode C maintains `jira_context` through the session and writes back in Phase 7.5/7.6.
- **Phase 2** decides upgrade strategy from the dep tree: `direct_bump` / `bump_override` / `bump_parent` / `lock_only` / etc. Go has its own MVS-aware variants (`bump_indirect`, `add_replace`). The strategy chosen here drives the Phase 5 commands.
- **Phase 3** does dual-track breaking-change analysis: `fetch_changelog.py` + `git_diff.sh` (with Go/JS variants), cross-referenced. Reports must cite source URLs and commit SHAs verbatim — the templates/`report_structure.md` enforces this.
- **Phase 4** uses `ast_scanner*` to locate every import/symbol-use of the target package, scoped to actual breaking changes from Phase 3.
- **Phase 5** is the only phase that mutates files. Always behind a feature branch; environment is snapshotted (`snapshot_env*.sh`) first. For lockfile-only fallback paths, `validate_lockfile.sh` / `validate_modfile_go.sh` run after.
- **Phase 6** runs the test suite — layered (affected tests first, full suite second) with a 3-iteration cap on the fix loop.
- **Phase 7** writes the report, commit, PR, and (Jira-triggered) ticket comment + transition.

### Two non-obvious invariants worth knowing

- **`pkg_manager_bin`** (from `detect_env_js.sh`) — corepack-managed yarn is **not** in PATH; the detected binary path (e.g. `node .yarn/releases/yarn-3.8.2.cjs`) must be used everywhere. Don't hardcode `yarn` / `npm` in new scripts.
- **Dependency-file updates are tool-specific** — see `references/IMPORTANT_DEPENDENCY_UPDATE.md`. Most critical: use `poetry add pkg@version` (not `poetry update`) and `uv add "pkg>=version"` (not `uv lock --upgrade-package`) — both `update` / `--upgrade-package` only touch the lockfile and leave `pyproject.toml` stale. Plain `pip` requires **manual** editing of `requirements.txt` / `pyproject.toml`.

### References are loaded lazily

`SKILL.md` does not inline every detail — it directs Claude to read specific files under `references/` on demand (e.g. only read `references/jira_workflow.md` when Phase 1 mode C is hit, only read `references/go_major_version_paths.md` when a Go v1→v2 jump is detected). When adding a new pattern that is large or rarely needed, prefer adding a new `references/*.md` and a one-line pointer in `SKILL.md` over inlining.

## Conventions for scripts

- **Python**: `#!/usr/bin/env python3` shebang, type hints, JSON to stdout / errors to stderr, black + ruff clean, target Python 3.8.
- **Bash**: `#!/usr/bin/env bash` + `set -euo pipefail`, errors to stderr (`>&2`), use `jq` for JSON.
- **JS**: helpers live in `package-upgrade/scripts/`, deps declared in the inner `package.json`.
- **All**: chmod +x after creation — `install.sh` does this on install but local `uv run` and `bash` need it during development.
