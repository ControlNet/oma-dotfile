## Rules

- Code/comments/identifiers in English. Reply in the user’s language unless explicitly requested otherwise.
- When giving terminal steps, always include copy-pastable CLI commands.
- Never include secrets/tokens/keys in code, logs, docs, or gists. Assume public by default; use env vars and mention .gitignore/.env.local.
- Prefer minimal, reviewable patches; avoid large refactors unless asked.
- For non-trivial changes: include exact verification commands (lint/test/run) and expected outcome/signals (what should pass / what to look for).
- Warn before any destructive action (delete/overwrite/migration/force push).
- Only modify project-level AGENTS.md when explicitly asked to change project rules.
- Use pixi or conda to manage Python environments. Prevent installing packages to system-level Python.
- For Python work: if the Python environment is not explicitly specified or is ambiguous, ask the user to confirm (pixi/conda + env name/path). Once confirmed, persist the environment choice in project-level AGENTS.md (as an "Environment" memory block) and create/update a repo-root LSP config (pyrightconfig.json) so imports/types resolve in that environment.
- Test-driven development is preferred.
