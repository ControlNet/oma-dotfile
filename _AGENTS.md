## Rules

- Code/comments/identifiers in English. Reply in the user's language unless explicitly requested otherwise.
- When giving terminal steps, always include copy-pastable CLI commands.
- Never include secrets/tokens/keys in code, logs, docs, or gists. Assume public by default; use env vars and mention .gitignore/.env.local.
- Prefer minimal, reviewable patches; avoid large refactors unless asked.
- For non-trivial changes: include exact verification commands (lint/test/run) and expected outcome/signals (what should pass / what to look for).
- For non-trivial implementation work, load the beads skill and track execution in Beads (bd): create or continue an issue, keep current progress + next step in the issue, and close/update it with verification notes before ending the session.
- Warn before any destructive action (delete/overwrite/migration/force push).
- Only modify project-level AGENTS.md when explicitly asked to change project rules.
- Use pixi or conda to manage Python environments, unless the use of Python does not involve the 3rd-party packages. Prevent installing packages to system-level Python.
- For Python work: if the Python project requires 3rd-party packages, and the virtual Python environment is not explicitly specified or is ambiguous, ask the user to confirm (pixi/conda + env name/path). Once confirmed, persist the environment choice in project-level AGENTS.md (as an "Environment" memory block) and create/update a repo-root LSP config (pyrightconfig.json) so imports/types resolve in that environment.
- Test-driven development is preferred.
- Always check available skills before delegating or performing tasks directly. Use `load_skills=["skill-name"]` when delegating tasks that match a skill's domain (e.g., `github-cli` for GitHub inspection, `git-master` for git operations, `playwright` for browser automation).
