# Workflow: bd as the long-horizon TODO system

## Core rule
If it isn’t tracked in bd, it isn’t real work.
For agent sessions, start with `bd prime` and prefer `--json` whenever the next step depends on structured output.

## Setup / recovery path
- Fresh clone / repair / missing-database path: preview with `bd bootstrap --dry-run --json`, then use `bd bootstrap`.
- Brand-new explicit initialization: `bd init --skip-hooks` (or `bd init --contributor --skip-hooks` / `bd init --team --skip-hooks` when role-specific setup matters).
- Legacy repo with `.beads/issues.jsonl`: import with `bd init --from-jsonl --skip-hooks` instead of creating a fresh empty database.

## Working loop (single-issue focus)
1) Orient: run `bd prime`, then `bd ready --json`, and pick exactly one issue to focus on.
2) Inspect + claim: use `bd show <id> --json` if needed, then `bd update <id> --claim --json`.
3) Execute work.
4) Whenever you discover follow-up work:
   - Create an issue immediately with explicit context (`--description`).
   - Link provenance with `--deps discovered-from:<current-id>`.
   - Use `--parent <epic-id>` when you are breaking down larger work.
5) Keep the issue current without interactive editors:
   - `bd update <id> --notes "Current status" --json`
   - `bd update <id> --append-notes "Next step" --json`
   - `bd comments add <id> "Short running note"`
   - Do **not** use `bd edit` from an agent session.
6) Finish:
   - Close the issue if done: `bd close <id> --reason "..." --json` (or `bd done <id> --reason "..." --json`)
   - If partial, leave it open and append the exact next step.

## Dependency patterns
- Use `blocks` when order is mandatory (hard prerequisite).
- Use `related` when it is contextually connected but not blocking.
- Use `parent-child` for breakdown and hierarchy.
- Use `discovered-from` to preserve provenance when work is uncovered during implementation.

## Legacy repositories
If current `bd` reports that no beads database exists, but the repo still has a legacy `.beads/issues.jsonl` layout, do not keep using stale JSONL-era workflow docs.

Import the legacy data into the current Dolt-backed setup instead:

```
bd init --from-jsonl --skip-hooks
bd doctor --migration=post --json
```

## Suboptimal solutions (tech debt tracking)
When implementing a workaround or partial fix due to external constraints:

1) Add the `suboptimal` label to the issue:
   ```
   bd label add <id> suboptimal
   ```

2) Create a follow-up issue for the proper fix (often blocked on upstream):
   ```
   bd create "Upstream: <what's needed>" --description="Constraint + ideal fix" -t task -p 3 --json
   ```

3) Link them with a `related` dependency:
   ```
   bd dep add <original-id> <upstream-id> --type related
   ```

4) Close the original with a reason that explains the limitation:
   ```
   bd close <id> --reason "Partial fix: <what was done>. Full fix blocked on <upstream-id>. Label: suboptimal." --json
   ```

5) Review the label later with your preferred list/filter command, for example:
   ```
   bd list --status open --json
   ```

## Session-ending protocol ("landing the plane")
Before ending a session:
- File/update remaining TODOs as bd issues (create new ones if needed).
- Close completed issues or update the current issue with notes + next step.
- Run quality gates if code changed (tests/linters/build).
- Sync via Dolt when a remote is configured: `bd dolt push` to publish your changes, `bd dolt pull` to consume teammates' updates.
- Keep hooks current with `bd hooks install`, and prefer `bd prime` / `bd setup <tool>` for dynamic workflow injection instead of copying large static instructions into every session. If you started with `--skip-hooks`, this is the explicit opt-in step that adds them later.
- Provide a short “Next session prompt” that starts from `bd prime` or `bd ready --json`.
