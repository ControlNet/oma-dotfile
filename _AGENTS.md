## Rules

- Code/comments/identifiers in English. Reply in the user’s language unless explicitly requested otherwise.
- When giving terminal steps, always include copy-pastable CLI commands.
- Never include secrets/tokens/keys in code, logs, docs, or gists. Assume public by default; use env vars and mention .gitignore/.env.local.
- Prefer minimal, reviewable patches; avoid large refactors unless asked.
- For non-trivial changes: include exact verification commands (lint/test/run) and expected outcome/signals (what should pass / what to look for).
- Warn before any destructive action (delete/overwrite/migration/force push).
- Only modify project-level AGENTS.md when explicitly asked to change project rules.

## Beads (bd) task tracking

- Prefer using the `beads` (bd) command to track work for any non-trivial request.
- Before starting bug investigation/fix: run `bd search` to check for existing related issues; if found, update/comment there instead of creating duplicates.
- When fixing a bug: add a regression test first (or alongside the fix) and run the minimal test/lint commands to verify it actually catches the bug and prevents regressions.
- Work on ONE Beads issue at a time: pick from `bd ready`, keep status/progress in the issue, and close it with:
  - what changed, verification commands (and what passed), and the next step (if any).
- Record design decisions only when they matter: include “Alternatives considered” with 1–3 options and why the chosen one was selected. Do not log every minor thought.
- If you change behavior/API/config, update the relevant docs (e.g., README.md) in the same PR/commit.
- After `bd close`, create a focused git commit that includes only the related changes (keep diffs small and reviewable).
