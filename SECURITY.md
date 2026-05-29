# Security Policy

This repository is the source for the **`package-upgrade` Claude Code Skill** — it
is not a deployed service or a published library. It ships shell / Python / JS / Go
helper scripts that run **locally on a developer's machine** through Claude Code, and
that drive package-manager commands, edit dependency files, and handle auth tokens.
Security here is mostly about the safety of those local operations and the integrity
of what `install.sh` copies into `~/.claude/skills/`.

## Supported Versions

The skill is distributed via `git clone` + `install.sh`, so there is effectively one
supported line: the latest `master`. Security fixes land there and are picked up the
next time you re-run `install.sh`.

| Version            | Supported          |
| ------------------ | ------------------ |
| `master` (latest)  | :white_check_mark: |
| Older tags / forks | :x:                |

If you installed previously, re-run `bash install.sh` (or `install.bat`) to pull the
current scripts before relying on a fix.

## What counts as a vulnerability here

Because the skill executes locally and touches your environment, we treat the
following as in-scope security issues:

- **Command / code injection** in any helper script (`scripts/**`,
  `install.sh`, `grant_permissions.py`, etc.) — e.g. unsanitized package names,
  CVE IDs, Jira URLs, or changelog content reaching a shell.
- **Secret leakage** — auth tokens written outside `save_token.sh` (which enforces
  `chmod 600` + `.gitignore`), tokens echoed to logs/stdout, or `.env.*` files
  committed.
- **Path traversal / arbitrary file write** when locating or editing dependency
  files, snapshots, or reports.
- **Supply-chain integrity** of the install path — anything that lets `install.sh`
  copy or fetch unexpected content into `~/.claude/skills/`, or untrusted code in the
  inner `scripts/javascript/package.json` dependencies.
- **Over-broad permissions** granted to Claude Code via `grant_permissions.py` /
  `settings.json`.

Out of scope: vulnerabilities in the **third-party packages this skill helps you
upgrade** (report those upstream), and issues in Claude Code itself
(report to Anthropic).

## Reporting a Vulnerability

**Please do not open a public issue for security problems.**

Use GitHub's private vulnerability reporting:

1. Go to the **Security** tab of
   `https://github.com/millerlai/auto-package-migration`.
2. Click **Report a vulnerability** (Privately report a vulnerability).
3. Include: affected script/file, repro steps or a minimal PoC, the impact, and your
   environment (OS, shell, language/tool versions).

If private reporting is unavailable to you, open a regular issue **without** any
sensitive details (no PoC, no secrets) asking a maintainer to reach out, and we'll
follow up through a private channel.

### What to expect

- **Acknowledgement:** within ~5 business days.
- **Assessment:** we'll confirm the report, ask follow-ups if needed, and agree on
  severity.
- **Fix:** accepted issues are patched on `master`; you'll be credited in the fix
  unless you prefer to stay anonymous.
- **Decline:** if it's out of scope or not reproducible, we'll explain why.

Please give us reasonable time to ship a fix before any public disclosure.
