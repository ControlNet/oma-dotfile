# Tokscale: how projects and workspaces treat git worktrees

Checked 2026-10-25 against tokscale `master` (991a89c) and release v4.20.1.

## Two different views

- **TUI Projects tab: always merged.** Its rows come from
  `workspace_bucket(msg, WorktreeRollup::MergeIntoRepo, ...)`, hard-coded in
  `crates/tokscale-cli/src/tui/data/mod.rs`, so every worktree of a repo lands in the
  repo's row. There is no switch for it. Codex chats with no workspace get their own row.
- **Workspace grouping (`--group-by workspace,model`, TUI group `workspace,model`):
  separate by default.** `WorktreeRollup::default()` is `Separate`: one row per
  worktree, labeled `repo ⑃ worktree`.
  - CLI: add `--merge-worktrees`, e.g.
    `tokscale models --group-by workspace,model --merge-worktrees --month`.
  - TUI: press `w` while grouped by `workspace,model`; the footer shows `[w:repos]`
    (merged) or `[w:worktrees]`. Not persisted, and there is no settings.json key.
- Other groupings (model, client, session...) carry no workspace at all.

## How a worktree is mapped to its repo (`crates/tokscale-core/src/sessions/mod.rs`)

1. Path markers: anything below `<repo>/.claude/worktrees/` or `<repo>/.git/worktrees/`
   rolls up to `<repo>` (outermost marker wins for nested worktrees).
2. A worktree checked out elsewhere (`git worktree add ../x`, or tool-managed dirs such
   as Codex's or OMO's own worktree folders) is resolved by reading its `.git` pointer
   file (`gitdir: <repo>/.git/worktrees/<name>`). This needs the directory to still
   exist and the key to be an absolute path.
3. Claude Code slugs keep the encoded marker (`--claude-worktrees-`), so a deleted
   `.claude/worktrees` worktree still merges from the slug string.

Limits: a deleted worktree outside the repo (case 2) can no longer be resolved and
stays its own row; a repo reached through a symlink and through its target stays two
rows (keys compare as strings). Totals never change, only how rows are split.
