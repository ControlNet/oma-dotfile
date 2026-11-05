# `npx skills` (vercel-labs/skills) install directories (checked 2026-11-05, skills 1.7.6)

These notes cover where the skills CLI can put skills, so that `pull.py` can keep using the
existing per-agent skill directories.

## Fixed global directories

There is no `--dir`/`--path` flag in 1.7.6. Each agent has a hard-coded `globalSkillsDir`:

| Agent id | Global skills dir |
| --- | --- |
| `opencode` | `$XDG_CONFIG_HOME/opencode/skills` (default `~/.config/opencode/skills`) |
| `claude-code` | `$CLAUDE_CONFIG_DIR/skills` (default `~/.claude/skills`) |
| `codex`, `pi`, `universal`, ... | `~/.agents/skills`. `CODEX_HOME` is only used to detect Codex. |
| OMP, OMO Native | Not supported as agents ([issue #1535](https://github.com/vercel-labs/skills/issues/1535) asks for OMP). |

Custom directories are still pending upstream:
[issue #222](https://github.com/vercel-labs/skills/issues/222),
[PR #2302 `--dir`](https://github.com/vercel-labs/skills/pull/2302),
[PR #2087 `--skills-dir`](https://github.com/vercel-labs/skills/pull/2087). Both PRs were open and
unmerged on 2026-11-05.

## Readers of `~/.agents/skills`

- Codex 0.166 reads both `~/.codex/skills` ("codex-home-skills") and `~/.agents/skills`
  ("user-agent-skills").
- OMP 18.14.1 and OMO Native read `~/.agents/skills` as well as their own agent dir.
- A skill present in both places can therefore load twice.

## Install modes

- Default (symlink): the skill is copied to the canonical `~/.agents/skills/<name>`, and each
  non-universal agent dir gets a symlink to it.
- `--copy`: each selected non-universal agent gets a real copy in its own dir, and **nothing is
  written to `~/.agents/skills`**.

## Workaround that works today: an env-relocatable agent with `--copy`

The `hermes-agent` target uses `$HERMES_HOME/skills`. The following was tested in a sandbox
(`HOME` pointed at a temp directory):

```bash
DISABLE_TELEMETRY=1 DO_NOT_TRACK=1 HERMES_HOME="$HOME/.omp/agent" \
  npx -y skills@1.7.6 add vercel-labs/skills -g -a hermes-agent -s find-skills --copy -y
```

Result: only `<HERMES_HOME>/skills/find-skills/SKILL.md` was written, and nothing appeared under
`~/.agents/skills`. The same works for `~/.codex` and `~/.omo/agent`. Other relocatable targets with
the same `<HOME_VAR>/skills` shape are `grok` (`GROK_HOME`), `mistral-vibe` (`VIBE_HOME`),
`autohand-code` (`AUTOHAND_HOME`) and `reasonix` (`REASONIX_HOME`). Use the agent *id* (for
example `hermes-agent`, not `hermes`).

## Lock file and updates

- Every `-g` install writes `$XDG_STATE_HOME/skills/.skill-lock.json`, or `~/.agents/.skill-lock.json`
  when `XDG_STATE_HOME` is unset. Entries are keyed by skill name only, with `source`, `sourceUrl`,
  `skillPath`, `skillFolderHash` and `installMode`. They do not record the agent or directory.
- `skills update -g` reinstalls through its own placement resolution. It does not know about the
  `HERMES_HOME` trick, so it cannot be relied on to refresh relocated installs. Re-running `add` is
  the update.
- `XDG_STATE_HOME` only moves the lock file, so a separate value keeps installs made by `pull.py` out
  of the lock that the user's own `npx skills update -g` reads.

## Other facts

- Telemetry goes to `https://www.skills.sh/tele/t` for public sources unless `DISABLE_TELEMETRY`
  or `DO_NOT_TRACK` is set.
- `npx skills add ControlNet/oma-dotfile -l` finds all 9 skills under `skills/`.
- Upstream sources of the vendored skills, as of 2026-11-05. The repo copies are older snapshots,
  and no local edits were seen:
  - `find-skills`: `vercel-labs/skills`
  - `web-design-guidelines`: `vercel-labs/agent-skills`
  - `ui-ux-pro-max`: `nextlevelbuilder/ui-ux-pro-max-skill`
  - `skill-creator`: closest to `openai/skills` `.system/skill-creator`
  - `frontend-claude`: renamed copy of `anthropics/skills` `frontend-design`
  - `frontend-codex`: no upstream found
