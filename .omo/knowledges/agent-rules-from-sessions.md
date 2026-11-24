# Finding shared rules from past agent sessions (2026-11-24)

`config/_AGENTS.md` gained eleven rules and three rewrites from two months of the user's own
messages to Claude Code, Codex and the Antigravity CLI. This is how, to repeat it later.

## Where the sessions are

| Agent | Files | User turns |
|---|---|---|
| Claude Code | `~/.claude/projects/<project>/<session>.jsonl` (subagents sit in subdirs) | rows `type: user`, not `isMeta`, not `isSidechain`; `message.content` is a string or a list of `text` blocks |
| Codex | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` | `response_item` rows with `payload.type: message`, `role: user`, `content[].text` |
| agy | `~/.gemini/antigravity-cli/brain/<id>/.system_generated/logs/transcript_full.jsonl` | rows `source: USER_EXPLICIT`, `type: USER_INPUT`; no timestamp per row |

Drop injected text before reading: `<system-reminder>` blocks, `# AGENTS.md instructions`,
`<environment_context>`, `<user_instructions>`, skill bodies (`Base directory for this skill:`),
slash-command echoes, continuation summaries, and prompts repeated verbatim in many sessions
(summarizers and tests). Claude projects under `/tmp` are test sandboxes. Keep the tail
(about 500 chars) of the agent reply each turn answers: a correction means nothing without it.

## Scale and method

About 150 sessions and 2,700 user turns came to 3.5 MB of Markdown. It was split into 8 shards of
part files at most 100 KB each (long sessions split on turn boundaries) and read by an agy
`/swarm` with one analyst per shard, each writing candidate rules with verbatim quotes. A script
then checked every quote against its source file (698 of 698 found). Session counts summed across
shards are approximate: a long session split across shards counts twice.

## What the user decided

- Kept out: an "evidence first" rule (already said in many places) and "never create tags,
  releases, issues or PRs" (some repos run on issues and PRs).
- Parallel fixes get one worktree and branch each, merged back, then the worktrees and the local
  and remote branches are deleted without asking. Otherwise work on the current branch.
- Writing for others (README, docs, release notes, PR/issue text, papers) goes through
  `ccf-humanization`; commit messages and chat replies do not. Commits use Conventional Commits.
- Privacy covers everything committed or posted, but the configured git author name and email
  stay: an agent once stripped them for privacy.
