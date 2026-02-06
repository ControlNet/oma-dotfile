# Workflow: bd as the TODO system

## Core rule
If it’s not tracked in bd, it is not a real TODO.
Use plain-output command forms in this workflow; append `--json` only when an agent/script needs machine-readable output.

## Working loop (single-issue focus)
1) Orient: `bd ready` and pick exactly one issue to focus on.
2) Mark: `bd update <id> --status in_progress`
3) Execute work.
4) Whenever you discover follow-up work:
   - Create an issue immediately (bug/task/feature).
   - Link it back with `--type discovered-from`.
5) Finish:
   - Close the issue if done, otherwise keep it in progress with updated notes.

## Dependency patterns
- Use `blocks` when order is mandatory (hard prerequisite).
- Use `related` when it is contextually connected but not blocking.
- Use parent-child for breakdown, and discovered-from to preserve provenance.

## Suboptimal solutions (tech debt tracking)
When implementing a workaround or partial fix due to external constraints:

1) Add the `suboptimal` label to the issue:
   ```
   bd label add <id> suboptimal
   ```

2) Create a follow-up issue for the proper fix (often blocked on upstream):
   ```
   bd create "Upstream: <what's needed>" -t task -p 3
   bd comments add <new-id> "<explanation of constraint and ideal solution>"
   ```

3) Link them with `related` dependency:
   ```
   bd dep add <original-id> <upstream-id> --type related
   ```

4) Close the original with reason explaining the limitation:
   ```
   bd close <id> --reason "Partial fix: <what was done>. Full fix blocked on <upstream-id>. Label: suboptimal."
   ```

5) Query suboptimal issues later for tech debt review:
   ```
   bd list --label suboptimal
   ```

## Session-ending protocol ("landing the plane")
Before ending a session:
- File/update remaining TODOs as bd issues (create new ones if needed).
- Close completed issues; update statuses for partial work.
- Run quality gates if code changed (tests/linters/build).
- Sync issue data via git workflow (commit/push the beads JSONL changes if present).
- Provide a short “Next session prompt” that starts from `bd ready`.
