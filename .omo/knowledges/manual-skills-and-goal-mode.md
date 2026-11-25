# Manual-only skills and goal mode

Checked on 2026-11-24 with Codex CLI 0.170.0, Claude Code (current docs) and agy 1.5.16.

## Turning off automatic invocation

| Agent | Setting | Manual call |
|---|---|---|
| Claude Code | `disable-model-invocation: true` in the SKILL.md frontmatter | `/name` |
| agy | the same frontmatter key; its built-in `swarm` skill uses it | `/name` |
| Codex | `agents/openai.yaml` next to SKILL.md with `policy:` / `allow_implicit_invocation: false`. Codex does not read the frontmatter key. Its own `review-agent` skill is set up this way | `$name` or `/skills` |

Sources: the Codex skill-creator reference shipped with the CLI
(`~/.codex/skills/.system/skill-creator/references/openai_yaml.md`),
<https://learn.chatgpt.com/docs/build-skills>, <https://code.claude.com/docs/en/skills>.

## Why the repo's manual skills do not use it

Goal mode: Codex `/goal` (enable with `codex features enable goals` if it is missing) and Claude
Code `/goal`. No goal mode was found in agy 1.5.16's built-in skills or guide.

When a Codex goal objective contains `$name`, Codex does not inject the skill body the way it does
for `$name` in an ordinary message. A session log showed the agent found the skill in the listed
skills and read its SKILL.md on its own. With `allow_implicit_invocation: false` the skill is not
listed, so a goal that names it may never load it.

Claude Code's goal evaluator is a small model that sees only the conversation; it runs no commands.
After compaction Claude Code may keep only the start of an invoked skill.

So `auto-review-loop` and `contribute-issue-to-merge` set no invocation flag. Their descriptions end
with "Use only when the user invokes it by name ...", which keeps them listed (and reachable from a
goal) while agents leave them alone otherwise, as with the herdr skill. Each puts its stop condition
and a one-line status per round at the top of the body, so a goal evaluator can judge progress and
the rule survives compaction.

Usage:

```
/goal $auto-review-loop      # Codex
/goal /auto-review-loop      # Claude Code
```

The stop condition lives in the skill, which tells the agent to end with `stop condition met`, so
the goal text only needs extra limits such as a path or a round cap.

## Verified on 2026-11-25

Tested on a throwaway repo, with each CLI in a herdr pane, by checking the session logs
(`~/.codex/sessions/...`, `~/.claude/projects/...`) for the skill being loaded:

| Test | Codex 0.170.0 | Claude Code |
|---|---|---|
| "Review this repository for bugs and fix what you find" | listed, not loaded | listed, no `Skill` call |
| `$auto-review-loop ...` in a normal message | body injected | (not run) |
| `/goal $auto-review-loop ...` (Claude: `/goal /auto-review-loop ...`) | not injected; agent read SKILL.md itself; goal achieved | `Skill` tool called; goal achieved |

Bare `/goal $auto-review-loop` (Codex 0.172.0) and `/goal /auto-review-loop` (Claude Code), on
a repo with a local remote, one planted bug and no CI: both fixed and pushed the bug, ran another
round that found nothing, printed `... CI none at <sha>, stop condition met`, and the goal ended
by itself (about 3 minutes each). Inside Herdr, the Claude agent started its Codex reviewer in a
sibling pane and asked before accepting Codex's folder-trust prompt.

In Codex, a prompt that starts with `$name` sent through `herdr agent prompt` can stay in the
composer (the skill picker takes the Enter); send `enter` once more.

If a goal ever does not pick up the skill, call the skill in a normal message first, then set
`/goal` with only the stop condition.
