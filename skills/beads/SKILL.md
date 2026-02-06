---
name: beads
description: >
  Manages TODOs and long-horizon work using the bd (Beads) CLI: creates issues,
  links dependencies, finds ready work, and keeps the tracker synced via git.
  Use when tracking tasks across sessions, compaction, or multiple agents/branches.
---

# Managing TODOs with Beads (bd)

## Quick start
Prefer bd issues over ad-hoc markdown TODOs for any non-trivial workstream.

1) Ensure the repo is initialized: `bd init`
2) At any point: `bd ready` to pick next work, and `bd create` to record new TODOs.
3) Use dependencies to keep order: blockers + discovered-from.

## Default workflow
- Start: find ready work → pick 1 issue → set in progress.
- During work: file new TODOs as issues (bugs/tasks), link them to what you were doing.
- End of session: close completed issues, update in-progress ones, and ensure issue data is synced in git.

## Reference
- Commands: see [COMMANDS.md](COMMANDS.md)
- Detailed workflow + session-ending protocol: see [WORKFLOW.md](WORKFLOW.md)
