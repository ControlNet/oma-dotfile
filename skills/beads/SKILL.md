---
name: beads
description: >
  Manages TODOs and long-horizon work using the bd (Beads) CLI: creates issues,
  links dependencies, finds ready work, and keeps the tracker synced via git and dolt.
  Use when tracking tasks across sessions, compaction, or multiple agents/branches.
---

# Managing TODOs with Beads (bd)

## Quick start
Prefer bd issues over ad-hoc markdown TODOs for any non-trivial workstream.

1) Ensure the repo is initialized:
   - Fresh clone / repair path: `bd bootstrap --dry-run --json`, then `bd bootstrap`
   - Standard repo: `bd init --skip-hooks`
   - Legacy `.beads/issues.jsonl` repo: `bd init --from-jsonl --skip-hooks`
   - OSS fork workflow: `bd init --contributor --skip-hooks`
   - Team/shared-branch workflow: `bd init --team --skip-hooks`
2) Load the live workflow context: `bd prime`
3) Find ready work with `bd ready --json`, and record new work with explicit context: `bd create "Short title" --description="Why this work exists" -t task -p 2 --json`
4) When you begin work on an issue, claim it atomically: `bd update <id> --claim --json`

## Default workflow
- Start: `bd prime`, then `bd ready --json`; inspect with `bd show <id> --json` when needed.
- Claim work with `bd update <id> --claim --json` instead of manually setting status flags.
- During work: file discovered TODOs immediately as issues (bugs/tasks/features), include `--description`, and link provenance with `--deps discovered-from:<current-id>`.
- Update issues non-interactively with `bd update` flags or `bd comments add`; do not rely on `bd edit` from an agent session.
- End of session: close completed issues with `bd close <id> --reason "..." --json` (or `bd done <id> --reason "..." --json`), leave partial work open with fresh notes/next steps, and sync via Dolt (`bd dolt push` / `bd dolt pull`) or current hooks. If you initialized with `--skip-hooks`, install them later with `bd hooks install` when you want hook-managed sync/context injection.

## Reference
- Commands: see [COMMANDS.md](COMMANDS.md)
- Detailed workflow + session-ending protocol: see [WORKFLOW.md](WORKFLOW.md)
- Minimal AGENTS snippet from upstream: `bd onboard`
- Diagnostics/docs helpers: `bd context`, `bd help --list`, `bd help --doc <command>`
