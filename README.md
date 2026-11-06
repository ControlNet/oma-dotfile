# oma-dotfile

My agent configs for OpenCode/OMO, OMO Native, oh-my-pi (OMP), Codex and Claude Code.

## Install

Requires Python 3.10+ and Git; skills also need Node.js (`npx`).

```bash
curl -fsSL https://raw.githubusercontent.com/ControlNet/oma-dotfile/master/pull.py | python3
```

```powershell
(Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/ControlNet/oma-dotfile/master/pull.py' -UseBasicParsing).Content | python
```

- Only detected agents are configured; `--all` or `INSTALL_ALL=1` installs all of them.
- Changed config files are backed up as `*.bak-<timestamp>`; `NO_BACKUP=1` skips this.

## OpenAI OAuth

Models go through a third-party gateway by default. To use OpenAI OAuth, append `- --oauth`:

```bash
curl -fsSL https://raw.githubusercontent.com/ControlNet/oma-dotfile/master/pull.py | python3 - --oauth
```

```powershell
(Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/ControlNet/oma-dotfile/master/pull.py' -UseBasicParsing).Content | python - --oauth
```

Then sign in: `codex login`, `opencode auth login --provider openai` (choose ChatGPT),
`/login openai-codex` in OMP, `/login chatgpt-subscription` in OMO Native.
Rerun without `--oauth` to switch back.

## Environment variables

| Variable | Use |
|---|---|
| `CODEX_BASE_URL` (with `/v1`), `CODEX_API_TOKEN` | Gateway, default mode |
| `OPENCODE_DISABLE_CLAUDE_CODE=1` | Recommended; OpenCode ignores Claude Code config |
| `GITHUB_PERSONAL_ACCESS_TOKEN` | gh tools |
| `NOTION_API_TOKEN` | notion-api skill |
| `GOTIFY_URL`, `GOTIFY_TOKEN_FOR_OPENCODE` | Gotify |
| `GOTIFY_TOKEN_FOR_CODEX`, `GOTIFY_TOKEN_FOR_OMP`, `GOTIFY_TOKEN_FOR_CLAUDE` | Per-agent token; defaults to `GOTIFY_TOKEN_FOR_OPENCODE` |
| `OPENCODE_NOTIFY_TITLE`, `CODEX_NOTIFY_TITLE`, `OMP_NOTIFY_TITLE`, `CLAUDE_NOTIFY_TITLE` | Gotify title; default `<Agent> :: <project>@<hostname>` |
| `GOTIFY_NOTIFY_SUMMARIZER_MODEL`, `GOTIFY_NOTIFY_SUMMARIZER_ENDPOINT`, `GOTIFY_NOTIFY_SUMMARIZER_API_KEY` | Summarize notifications with an OpenAI-compatible API |
| `OMP_WAKATIME_SYNC=false`, `OMP_WAKATIME_SYNC_INTERVAL_SEC` (default 120) | OMP WakaTime sync |
| `WAKATIME_HOME` | Directory of `.wakatime.cfg` |
| `WAKATIME_API_KEY`, `WAKATIME_API_URL` | Written to `.wakatime.cfg`; wakatime-cli reads only the key itself |
| `CONFIG_DIR`, `CODEX_DIR`/`CODEX_HOME`, `CLAUDE_CONFIG_DIR`, `OMP_AGENT_DIR`/`PI_CODING_AGENT_DIR`, `OMO_CODING_AGENT_DIR` | Override install directories |

## Installed files

| Agent | Directory | Contents |
|---|---|---|
| OpenCode/OMO | `~/.config/opencode`, `~/.omo/omo.jsonc` | Config, plugins; OMO settings under `"[opencode]"` |
| OMO Native | `~/.omo/agent` | `AGENTS.md`, `models.json`, `settings.json` (ignores `~/.claude` rules); routing under `"[native]"` in `omo.jsonc`. With `herdr`, `node` and `npm` found: [omo-herdr-dag](https://github.com/jc01rho/omo-herdr-dag) (pinned, upstream installer, reinstalled only when changed; English by default, `npx omo-herdr-dag@<version> install --lang zh-cn` once to switch) |
| OMP | `~/.omp/agent` | `AGENTS.md`, config, models, Gotify and WakaTime extensions |
| Codex | `~/.codex` | `AGENTS.md`, Gotify notifier, WakaTime plugin; `config.toml` disables the bundled `skill-creator` in favour of the shared one |
| Claude Code | `~/.claude` | Rule `rules/oma-dotfile.md`, Gotify plugin, WakaTime plugin |
| Tokscale | Tokscale `settings.json` | Model aliases from `tokscale_model_alias.json` |
| Skills | `~/.agents/skills` | See [Skills](#skills) |

## Skills

Installed with the [skills CLI](https://github.com/vercel-labs/skills) (`npx`, so Node.js is
needed) into `~/.agents/skills`, which OpenCode, OMO Native, OMP and Codex all read. Claude Code
does not read it and gets none of these skills yet.

| Source | Skills |
|---|---|
| This repo's `skills/` | `frontend-codex`, `github-cli`, `notion-api`, `secret-guard` |
| `vercel-labs/skills` | `find-skills` |
| `vercel-labs/agent-skills` | `web-design-guidelines` |
| `anthropics/skills` | `frontend-design`, `skill-creator` |
| `nextlevelbuilder/ui-ux-pro-max-skill` | `ui-ux-pro-max` |

- Every run installs the latest version. `npx skills update -g` also updates them, since they are
  listed in `~/.agents/.skill-lock.json` with any other skills you added.
- An existing skill with the same name in `~/.agents/skills` is replaced.
- Copies with these names left by older versions of `pull.py` in `~/.config/opencode/skills`,
  `~/.codex/skills`, `~/.omp/agent/skills` and `~/.omo/agent/skills` are deleted once the new copy
  is installed, so no skill loads twice. The old `frontend-claude` goes too once `frontend-design`
  is in. Other skills in those folders are left alone.
- Skills are skipped with a warning when `npx` is missing or offline; old copies then stay.
- To add a third-party skill, add its source to `UPSTREAM_SKILLS` in `pull.py`. To add your own,
  put it in `skills/` and push.

## OMP Gotify notifications

Only the main agent sends notifications; subagent completions, errors and questions are silent.
During an active goal, intermediate agent turns do not report success. A completed goal notifies
after its terminal turn settles, not when the `goal complete` tool first runs. Main-agent questions
and terminal errors still notify during goal execution.

Pausing or dropping a goal does not report success; subsequent ordinary turns notify normally.
Goal suppression is restored when loading, switching, branching or navigating sessions.
After updating the installed extension, restart OMP to load the new behavior.

## WakaTime

Set `WAKATIME_API_KEY` (and `WAKATIME_API_URL` for a self-hosted server) before running
`pull.py`; it writes them to `api_key`/`api_url` under `[settings]` in `~/.wakatime.cfg`, replacing
those two values and keeping the rest of the file. Without them, edit the cfg by hand. OpenCode uses `opencode-wakatime`; Codex and Claude Code
use the official plugins. OMP runs `wakatime-cli --sync-ai-activity` after each agent run, which
needs an installed `wakatime-cli` v2.24.0+.

## Logs

| Agent | Log |
|---|---|
| OpenCode | `~/.local/share/opencode/gotify-notify.log` |
| OMP | `~/.omp/logs/gotify-notify.log`, `~/.omp/logs/wakatime-sync.log` |
| Codex | `~/.codex/log/gotify-notify.log` |
| Claude Code | `~/.claude/logs/gotify-notify.log` |
