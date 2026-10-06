# oma-dotfile

My agent configs for OpenCode/OMO, OMO Native, oh-my-pi (OMP), Codex and Claude Code.

## Install

Requires Python 3.10+ and Git.

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
| `CONFIG_DIR`, `CODEX_DIR`/`CODEX_HOME`, `CLAUDE_CONFIG_DIR`, `OMP_AGENT_DIR`/`PI_CODING_AGENT_DIR`, `OMO_CODING_AGENT_DIR` | Override install directories |

## Installed files

| Agent | Directory | Contents |
|---|---|---|
| OpenCode/OMO | `~/.config/opencode`, `~/.omo/omo.jsonc` | Config, plugins, skills; OMO settings under `"[opencode]"` |
| OMO Native | `~/.omo/agent` | `AGENTS.md`, `models.json`, `settings.json` (ignores `~/.claude` rules); routing under `"[native]"` in `omo.jsonc`. Run `omo setup` once to import skills |
| OMP | `~/.omp/agent` | Config, models, Gotify and WakaTime extensions |
| Codex | `~/.codex` | `AGENTS.md`, skills, Gotify notifier, WakaTime plugin |
| Claude Code | `~/.claude` | Rule `rules/oma-dotfile.md`, Gotify plugin, WakaTime plugin |
| Tokscale | Tokscale `settings.json` | Model aliases from `tokscale_model_alias.json` |

## WakaTime

Put the API key in `~/.wakatime.cfg`. OpenCode uses `opencode-wakatime`; Codex and Claude Code
use the official plugins. OMP runs `wakatime-cli --sync-ai-activity` after each agent run, which
needs an installed `wakatime-cli` v2.24.0+.

## Logs

| Agent | Log |
|---|---|
| OpenCode | `~/.local/share/opencode/gotify-notify.log` |
| OMP | `~/.omp/logs/gotify-notify.log`, `~/.omp/logs/wakatime-sync.log` |
| Codex | `~/.codex/log/gotify-notify.log` |
| Claude Code | `~/.claude/logs/gotify-notify.log` |
