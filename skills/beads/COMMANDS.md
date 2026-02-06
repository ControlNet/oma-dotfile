# Beads command cookbook (agent-friendly)

## Output mode convention
Use plain output by default in examples. Add `--json` only when command output is parsed by automation.

## Initialize
bd init

## Find next TODO
bd ready
bd ready --json

## Create TODO issues (prefer explicit type + priority)
bd create "Short title" -t task -p 2
bd create "Discovered bug" -t bug -p 0

## View + triage
bd list
bd show <issue-id>
bd dep tree <issue-id>

## Link dependencies
# Hard blocker (default is blocks)
bd dep add <issue-id> <blocker-id> --type blocks

# Discovered during other work (creates a traceable breadcrumb)
bd dep add <new-id> <parent-id> --type discovered-from

## Status transitions
bd update <issue-id> --status in_progress
bd close <issue-id> --reason "Implemented"

## Labels (for categorization and filtering)
bd label add <issue-id> <label>
bd label remove <issue-id> <label>
bd label list <issue-id>
bd label list-all

## Search and filter
bd search "<query>" --label <label>
bd search "<query>" --status open
bd list --label suboptimal

## Comments (for additional context)
bd comments add <issue-id> "<comment text>"

## Sync helpers
bd sync --status
bd sync
