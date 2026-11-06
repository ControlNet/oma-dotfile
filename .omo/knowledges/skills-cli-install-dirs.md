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
- OpenCode 1.19.4 scans `~/.agents` and `~/.claude` with the glob `skills/**/SKILL.md`, and walks up
  from the project for `.agents/skills` and `.claude/skills`.
  - `OPENCODE_DISABLE_EXTERNAL_SKILLS` turns both off.
  - `OPENCODE_DISABLE_CLAUDE_CODE` (recommended in README) or `OPENCODE_DISABLE_CLAUDE_CODE_SKILLS`
    turns off only the `.claude` part, so `~/.agents/skills` is still read.
  - Its own `~/.config/opencode/skills` is read as well.
- Claude Code 2.1.318 does **not** load `~/.agents/skills`. That path appears only in its Cursor
  import feature, which copies from there into `~/.claude/skills`. To reach Claude Code, the CLI's
  `-a claude-code` puts a link (or with `--copy`, a copy) in `~/.claude/skills`.
- A skill present both in `~/.agents/skills` and in an agent's own dir can therefore load twice.

## Install modes

- Default (symlink): the skill is copied to the canonical `~/.agents/skills/<name>`, and each
  non-universal agent dir gets a symlink to it.
- `--copy`: each selected non-universal agent gets a real copy in its own dir, and **nothing is
  written to `~/.agents/skills`**.

## Rejected workaround: borrowing another agent's home variable

**Do not use this in `pull.py`.** The user rejected it. It impersonates an unrelated agent
(Hermes), and on machines where that agent is really installed it could interfere with that
agent's work. It is recorded here only to explain why the approach is off the table.

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
- Upstream sources of the vendored skills, as of 2026-11-05. Check `git log -- skills/<name>`
  before replacing a copy with upstream; a plain diff against upstream cannot tell local edits from
  upstream drift.
  - `find-skills`: `vercel-labs/skills`. Unchanged since it was added.
  - `web-design-guidelines`: `vercel-labs/agent-skills`. Unchanged since it was added.
  - `skill-creator`: closest to `openai/skills` `.system/skill-creator`. Unchanged since it was added.
  - `ui-ux-pro-max`: `nextlevelbuilder/ui-ux-pro-max-skill`. **Locally modified** in two commits:
    project-scoped output and search changes, then keeping an existing Master on page runs.
    `tests/test_ui_ux_design_system.py` covers the second change. Upstream later added its own
    `force` guard against overwriting MASTER.md.
  - `frontend-claude`: renamed copy of `anthropics/skills` `frontend-design`.
  - `frontend-codex`: no upstream found.

## What `pull.py` does (since 2026-11-05)

- Step 12 runs when OpenCode, OMO Native, OMP or Codex is detected. For each source it runs
  `npx -y skills@1.7.6 add <source> -g -a universal -s <names...> -y --json` with
  `DISABLE_TELEMETRY=1 DO_NOT_TRACK=1`.
  - The `universal` agent has no directory of its own, so the skill is written once to
    `~/.agents/skills` and linked nowhere else.
  - The exit code is 0 even when a requested name is `skipped`. Success is therefore read per skill
    from the JSON (`status == "installed"`).
- Sources: `UPSTREAM_SKILLS` in `pull.py`, plus `REPO_OWNER/REPO_NAME#REPO_REV` for every
  `skills/<name>/SKILL.md` in the clone.
- After installing, it removes old copies with those names, plus `RETIRED_SKILLS` keys whose
  replacement installed, from the skills dirs of detected agents: `~/.config/opencode/skills`,
  `~/.codex/skills`, `~/.omp/agent/skills` and `~/.omo/agent/skills`. Nothing is removed when the
  install failed or `npx` is missing.
- `omo setup` imports only from OpenCode's own skills dir (`<opencode config>/skills`), so once that
  dir is cleaned it does not bring the duplicates back into `~/.omo/agent/skills`.
- `mikubaka88/CCFA-Skills` is installed whole with `ALL_SKILLS` (`-s '*'`), which picks up skills
  added upstream later (18 on 2026-11-06, `ccf-research-engineer` new). With `--json` it reports each
  skill as `installed`. A skill removed upstream is not uninstalled automatically.
- Claude Code (since 2026-11-06): when it is detected, every skill except
  `CLAUDE_CODE_EXCLUDED_SKILLS` (`skill-creator`, `find-skills`) is installed with
  `-a universal claude-code`, and `CLAUDE_CONFIG_DIR` is passed to the CLI.
  - The CLI writes the shared copy and a relative symlink `~/.claude/skills/<name>` ->
    `../../.agents/skills/<name>`. It replaces a same-named real directory there (the old hand-made
    `ccf-*` copies) and leaves other entries alone (`gotify-notify`).
  - Claude Code 2.1.318 loads symlinked skill dirs. This was checked from the `system/init` message
    of `claude -p --output-format stream-json --verbose`, which lists `skills` before the first
    model request; kill the process right after reading it.
  - `skills remove -g` without `-a` also deletes the Claude Code link.
- `herdrdev/herdr` (2026-11-06) has 4 skills: `herdr`, `herdr-pre-release-audit`,
  `herdr-throwaway-repro`, `triage`. Only `herdr` is installed. It is installed whether or not Herdr
  itself is installed, and its description limits it to explicit Herdr requests.
- Skills dropped from this repo are listed in `REMOVED_SKILLS` (`frontend-codex` since
  2026-11-06). Before installing, `pull.py` reads the lock file (`$XDG_STATE_HOME/skills/.skill-lock.json`,
  or `~/.agents/.skill-lock.json`) and runs `npx -y skills@1.7.6 remove <names> -g -y` only for names
  whose `source` is this repo. `remove` deletes `~/.agents/skills/<name>` and its lock entry. Running
  it again only prints "No matching skills found". Old per-agent copies with these names are deleted
  even when nothing is installed.
- Tests: `tests/test_agent_skills.py`. The installer tests patch `ensure_agent_skills`, because their
  fake `git clone` answers every `subprocess.run` call.

## Install speed (checked 2026-11-06)

- With nothing cached, step 12 took about 50 s for 8 CLI runs. CCFA alone took about 19 s.
- Why `add` is slow:
  - Sources whose owner is not on `BLOB_ALLOWED_OWNERS` (`vercel`, `vercel-labs`, `heygen-com`,
    `remotion-dev`) get a full `git clone --depth 1` into a temp dir on every run, changed or not.
    There is no sparse or partial clone (upstream feature request vercel-labs/skills#595, open).
  - `mikubaka88/CCFA-Skills` is 660 MB checked out (283 MB pack), almost all of it exemplar PDFs in
    `ccf-paper-writer/references/exemplars/papers` (up to 45 MB each). The clone alone takes about
    17 s, and the installed `ccf-paper-writer` is 282 MB.
  - Each run starts `npx` (about 1.2 s). `add` takes only `args[0]`, so sources cannot be batched,
    and parallel runs would race on the lock file (`addSkillToLock` reads and rewrites it).
  - The CLI reads only `GITHUB_TOKEN` or `GH_TOKEN`, not `gh auth`. Without a token the GitHub API
    allows 60 calls per hour, and each `add` makes a few. Once the quota is used up, vercel sources
    fall back to cloning too.
  - `skills update -g` does not help: without the API it clones every source to compare hashes.
- Fix in `pull.py`: skip a run whose source has not moved.
  - Before installing, `git ls-remote` fetches each source's commit (`HEAD`, or `refs/heads/<ref>`
    for `#ref`). The 8 sources take about 0.6 s in parallel. It uses no API quota.
  - After a complete install, the commit is saved next to the lock file in
    `.oma-dotfile-skill-commits.json`. The key is CLI version, source, agents and names.
  - A run is skipped when the commit matches and every skill is still present as
    `~/.agents/skills/<name>/SKILL.md`, and also in `<claude config>/skills/` for Claude Code runs.
    For `ALL_SKILLS`, the names are taken from the lock entries with that `source`.
  - An unknown commit (offline) or an incomplete install means the run happens again next time.
  - For `ALL_SKILLS`, a skill removed by hand (`npx skills remove <name> -g`) also loses its lock
    entry, so the rest still look complete and it comes back only with the source's next commit.
    Explicit names come back on the next run. Deleting the commits file forces a full reinstall.
  - Offline, each `ls-remote` can wait up to its 30 s timeout (in parallel) before the adds fail.
  - Measured in a sandbox home:
    - first run 48 s, second run 0.8 s;
    - after deleting one skill dir and one Claude link, only those two sources reinstalled (6 s).

## Checking which skills each agent discovers (no model calls)

| Agent | Command | Shows paths |
| --- | --- | --- |
| OpenCode 1.19.4 | `opencode debug skill` (JSON) | yes (`location`) |
| Codex 0.166 | `codex app-server` over stdio: send `initialize`, then the `initialized` notification, then `{"id":2,"method":"skills/list","params":{"cwds":["<dir>"],"forceReload":true}}` | yes (`path`, `scope`, `enabled`) |
| OMP 18.14.1 | `omp --mode rpc --no-session`, send `{"id":"c1","type":"get_available_commands"}`; skills are the entries with `source: "skill"`, named `skill:<name>` | no |
| OMO Native 5.1.27 | `omo --mode rpc --no-session`, send `{"id":"c1","type":"get_commands"}`; skills have `source: "skill"` and `sourceInfo.path` | yes |

Result after the migration on 2026-11-06:
- All four agents found the 9 shared skills from `~/.agents/skills`, and none of them found
  `frontend-claude`.
- Codex is the only agent that listed a duplicate: `skill-creator` comes both from
  `~/.agents/skills` (user scope) and from its built-in `~/.codex/skills/.system/skill-creator`
  (system scope), and both are enabled.
- Decision (2026-11-06): Codex keeps its bundled `skill-creator`. The Codex config step adds a
  `[[skills.config]]` entry with `path = "~/.agents/skills/skill-creator/SKILL.md"` (written as an
  absolute path) and `enabled = false` (`CODEX_DISABLED_SHARED_SKILLS` in `pull.py`). That config
  is read only by Codex, so the other agents still get the shared copy.
  - This is the format Codex's own app-server `skills/config/write` writes.
  - The path is used because a `name` selector would disable both copies. Codex also ignores an
    entry that has both `path` and `name`.
  - After the change, `skills/list` showed the shared copy disabled and the bundled one enabled.
  - Edge cases tested in a sandbox Codex 0.166: an entry whose path does not exist is accepted
    without errors, and an entry with both `path` and `name` is ignored (the skill stays enabled).
  - `pull.py` therefore never reuses an entry that also has `name`.
  - An inline or plain-table `skills.config` cannot be extended with `[[skills.config]]`, so the
    file is left alone with a warning. This covers `[skills] config = [...]`,
    `skills.config = ...`, `skills = { config = ... }`, `[skills.config]`, and
    `[skills.config.x]` before any entry.
  - When tomllib is present, an edit that would stop a previously valid file from parsing is
    dropped.
  - Paths are compared as plain strings. A different spelling of the same path only adds a
    second, harmless entry. Windows path matching was not tested.
