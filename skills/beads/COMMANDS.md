# Beads command cookbook (agent-friendly)

## Output mode convention
Prefer `--json` for agent-driven reads and writes. Use human-readable output only when a person is reading the result directly.

## Initialize / orient
bd bootstrap --dry-run --json
bd bootstrap
bd init --skip-hooks
bd init --contributor --skip-hooks
bd init --team --skip-hooks
bd init --from-jsonl --skip-hooks
# Destructive re-init: only with explicit confirmation and warning.
bd init --destroy-token DESTROY-<prefix> --skip-hooks
bd context --json
bd prime
bd hooks install
bd onboard
bd help --list
bd help --doc bootstrap

## Find and inspect work
bd ready --json
bd blocked --json
bd list --status open --json
bd show <issue-id> --json
bd dep tree <issue-id>
bd status --json

## Create issues (prefer explicit type + priority + description)
bd create "Short title" --description="Why this work exists" -t task -p 2 --json
bd create "Discovered bug" --description="What was found" -t bug -p 0 --deps discovered-from:<current-id> --json
bd create "Child task" --description="Follow-up from parent work" --parent <epic-id> -t task -p 2 --json
bd create "Design-heavy task" --description="Why design matters" --design-file design.md -t task -p 2 --json

## Claim / update / close
bd update <issue-id> --claim --json
bd update <issue-id> --notes "Current progress" --json
bd update <issue-id> --append-notes "Next step" --json
bd close <issue-id> --reason "Implemented" --json
bd done <issue-id> --reason "Implemented" --json
bd reopen <issue-id> --json

## Dependencies
# Hard blocker (default is blocks)
bd dep add <issue-id> <blocker-id> --type blocks

# Discovered during other work (creates a traceable breadcrumb)
bd dep add <new-id> <parent-id> --type discovered-from

# Soft relationship / context link
bd dep add <issue-id> <related-id> --type related

## Labels / comments / search
bd label add <issue-id> <label>
bd label remove <issue-id> <label>
bd label list <issue-id>
bd label list-all
# Use `comments` (plural): verified against current CLI help.
bd comments add <issue-id> "<comment text>"
bd search "<query>" --status open --json
bd search --external-contains "gh-123" --json

## Health / migration / Dolt sync
bd doctor
bd doctor --agent --json
bd migrate --inspect --json
bd dolt show
bd dolt remote add <name> <url>
bd dolt push
bd dolt pull

## Avoid teaching these as the primary workflow
- `bd sync` (stale / removed from current CLI help)
- JSONL-as-primary sync workflows
- `bd edit` from agent sessions
- Nomrally no need git hooks, but if you need, you can remove `--skip-hooks` from init commands or use `bd hooks install` after the fact.
