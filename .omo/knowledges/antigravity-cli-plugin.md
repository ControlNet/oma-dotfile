# Antigravity CLI (agy) plugin: rules and a Stop hook

Checked against agy 1.5.9 (2026-11-16) with a sandbox home and one real `agy -p` turn. Skills
are in `antigravity-cli-skills.md`. Local reference: the built-in skill
`~/.gemini/antigravity-cli/builtin/skills/agy-customizations/docs/` (`plugins.md`, `hooks.md`,
`rules.md`).

## What a plugin can carry

- `~/.gemini/config/plugins/<name>/` is discovered and enabled with no install step. Enabled
  state lives in `~/.gemini/config/config.json` under `plugins.<dir name>`, never in the plugin,
  so replacing the plugin dir keeps a user's `agy plugin disable`.
- `plugin.json` (marker; add `"version"` or `validate` warns), `rules/AGENTS.md` (loaded as
  always-on rules: a test rule changed the answer), `hooks.json` at the plugin root (not
  `hooks/hooks.json` for native plugins), `skills/`, `mcp_config.json`.
- Claude Code plugins cannot carry rules (`CLAUDE.md` in a plugin is not loaded) and Codex's
  plugin docs mention no AGENTS.md, so only agy gets everything from one plugin.

## Checks that need no login

- `agy plugin list --json`: each plugin with `enabled`, `rules` and `hooks` (hook names). A
  `hooks.json` that does not parse drops the `hooks` key; the plugin still lists.
- `agy plugin validate <dir> --json`: findings with `severity` error/warning/note; exits 1 on
  an error. It checks that a relative script in a hook command exists only when the first word
  is unquoted (`python3 scripts/x.py`), not after a quoted interpreter.
- No hook fires without a login: `agy -p` stops at "Waiting for authentication" before any
  `SessionStart` hook. CI cannot make agy run a hook.

## Hooks as agy runs them

- The command is a string run with `sh -c` (`cmd /c` on Windows) with the plugin dir as the
  working directory. Env has `PLUGIN_ROOT` and `PLUGIN_DATA`
  (`~/.gemini/antigravity-cli/plugin_data/<name>`).
- Synchronous, 30 s default timeout, stdout read as JSON. Print `{}`; a Stop hook printing
  `"decision": "continue"` keeps the agent going.
- Stop payload (camelCase): `hookEventName`, `conversationId`, `terminationReason`
  (`NO_TOOL_CALL` for a normal end, `ERROR`, `USER_CANCELED`, `MAX_*`...), `fullyIdle`,
  `continuationActive`, `executionNum`, `error`, `cwd`, `workspacePaths`, `lastUserInput`,
  `modelName`, `transcriptPath`, `artifactDirectoryPath`. No response text.
- `transcriptPath` is `~/.gemini/antigravity-cli/brain/<id>/.system_generated/logs/transcript.jsonl`,
  already holding the final step when Stop runs. Rows: `step_index`, `source` (`USER_EXPLICIT`,
  `MODEL`, `SYSTEM`), `type` (`USER_INPUT`, `PLANNER_RESPONSE`, `GENERIC`...), `content`,
  `tool_calls`. It cuts long fields at about 4 KB and lists them in `truncated_fields`;
  `transcript_full.jsonl` beside it has them whole.

## Windows

Not seen with a real agy: how it quotes the command for `cmd /c`. So the installed command is
`scripts\gotify-notify.cmd` (no quote, no space) and the `.cmd` quotes the interpreter.

cmd reads a batch file in the console's current code page, not a fixed one: written in the OEM
code page, `Zoë` was misread on GitHub's Windows runner ("The system
cannot find the path specified"). So the `.cmd` is ASCII, and a path with other letters starts
with `%USERPROFILE%`, `%LOCALAPPDATA%` and the like, which cmd expands as Unicode; `%` is
doubled. The CI install checks run the hook through `cmd /c` in the plugin dir with a Python
inside a home named `Zoë Example`.
