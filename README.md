# oma-dotfile

My agent configurations.

Requires Python 3.11+ and Git.

Default installation (third-party API mode), Linux/macOS:
```bash
curl -fsSL https://raw.githubusercontent.com/ControlNet/oma-dotfile/master/pull.py | python3
```

Windows (PowerShell):
```powershell
(Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/ControlNet/oma-dotfile/master/pull.py' -UseBasicParsing).Content | python
```

## Native OpenAI OAuth routing

The installer defaults to the existing third-party API configuration. To select
native OpenAI OAuth routing:

```bash
python3 pull.py --oauth
```

For a streamed installer, pass arguments after `-`:

```bash
curl -fsSL https://raw.githubusercontent.com/ControlNet/oma-dotfile/master/pull.py | python3 - --oauth
```

Windows (PowerShell):

```powershell
(Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/ControlNet/oma-dotfile/master/pull.py' -UseBasicParsing).Content | python - --oauth
```

- Codex stops selecting the managed `codex_api` provider; other provider
  selections and profiles remain unchanged.
- OpenCode retains any existing custom `codex` provider. OMO uses `openai/`
  model IDs while retaining reasoning settings.
- OMP uses native `openai-codex` models with the Sol/Luna context limits below.

OAuth mode does not require `CODEX_BASE_URL` or `CODEX_API_TOKEN`. It changes routing,
not credentials: log in through each agent, and verify that the retained model
IDs and reasoning levels are available to your account.

```bash
codex login
opencode auth login --provider openai
```

In OpenCode choose ChatGPT authentication. Inside OMP run `/login openai-codex`.
Existing explicit model selections, profiles, project overrides, and resumed
sessions can override defaults.

To restore the third-party configuration, rerun the installer without `--oauth`
with the gateway environment variables configured:

```bash
python3 pull.py
```

Codex automatically reselects `codex_api` when `CODEX_BASE_URL` is configured.

The installer always clones `REPO_REV` from GitHub. Local template changes must
be available in that remote revision before running it.

## Conditional installation

`pull.py` installs configuration only for agents present on the machine.

| Target | Steps | Detected by |
|---|---|---|
| OpenCode/OMO | OpenCode config, OMO config, plugins and skills | `opencode` executable |
| oh-my-pi | oh-my-pi config, extensions, models | `omp` executable |
| Codex | shared Codex assets, `config.toml` | `codex` executable |
| Claude Code | managed Claude Code plugin | `claude` executable |
| Tokscale | model aliases | `~/.config/tokscale` (or `$TOKSCALE_CONFIG_DIR`) exists |

OMO follows OpenCode detection; Tokscale is detected by its configuration directory.

To install everything regardless of detection, for example to pre-seed a machine before
installing the agents:

```bash
python3 pull.py --all
curl -fsSL https://raw.githubusercontent.com/ControlNet/oma-dotfile/master/pull.py | python3 - --all
```

## Environment variables

Installer environment variables:
- `INSTALL_ALL=1` (install every target without detecting agents; same as `--all`)

Recommended environment variables:
- `OPENCODE_DISABLE_CLAUDE_CODE=1` (disable claude-code support for opencode)

Optional environment variables:
- `CODEX_BASE_URL` (with `/v1`, required for the third-party API provider; not required by `--oauth`)
- `CODEX_API_TOKEN` (required for the third-party API provider; not required by `--oauth`)
- `GITHUB_PERSONAL_ACCESS_TOKEN` (used for gh tools)
- `NOTION_API_TOKEN` (used by the notion-api skill for Notion REST API calls)

Other optional environment variables:
- `GOTIFY_URL` (used for gotify notifications)
- `GOTIFY_TOKEN_FOR_OPENCODE` (used for gotify notifications)
  - `GOTIFY_TOKEN_FOR_CODEX` (optional; if missing, Codex notify falls back to `GOTIFY_TOKEN_FOR_OPENCODE`)
  - `GOTIFY_TOKEN_FOR_OMP` (optional; if missing, OMP notify falls back to `GOTIFY_TOKEN_FOR_OPENCODE`/`GOTIFY_TOKEN_FOR_CODEX`)
  - `GOTIFY_TOKEN_FOR_CLAUDE` (optional; if missing, Claude Code notify falls back to the other Gotify tokens)
- `OPENCODE_NOTIFY_TITLE`, `CODEX_NOTIFY_TITLE`, `OMP_NOTIFY_TITLE`, `CLAUDE_NOTIFY_TITLE` (optional; override the default Gotify title format `<Agent> :: <project>@<hostname>`)
- `GOTIFY_NOTIFY_SUMMARIZER_MODEL` (e.g., `gpt-5-nano`)
- `GOTIFY_NOTIFY_SUMMARIZER_ENDPOINT` (OpenAI-compatible endpoint, e.g., `https://api.openai.com/v1`)
- `GOTIFY_NOTIFY_SUMMARIZER_API_KEY` (API key used by summarizer requests)

Codex notify hook execution logs are written to:
- `~/.codex/log/gotify-notify.log`

Claude Code notify hook execution logs are written to:
- `~/.claude/logs/gotify-notify.log` (or `$CLAUDE_CONFIG_DIR/logs/gotify-notify.log`)

## OpenCode support

`pull.py` installs OpenCode config into `~/.config/opencode` (or `$CONFIG_DIR` if set).
For local `plugins/` and `skills/`, it replaces only same-named items shipped by this repo and preserves unrelated existing plugins/skills that users added locally.

## OMO support

`pull.py` installs the unified Oh My OpenAgent configuration as `~/.omo/omo.jsonc`.
OpenCode-specific OMO settings live under the `"[opencode]"` key in that file; `opencode.jsonc` remains the OpenCode core configuration.

Before overwriting an existing `omo.jsonc`, the installer creates a timestamped backup unless `NO_BACKUP=1` is set.
It also retires obsolete `~/.omo/config.json[c]` and OpenCode-directory `oh-my-opencode.json[c]` / `oh-my-openagent.json[c]` files by renaming them to timestamped backups, so only the current unified configuration remains active.

## Codex support

`pull.py` installs shared Codex assets into `~/.codex` (or `$CODEX_DIR` if set):
- `AGENTS.md`
- `skills/` (merge-copy, preserves unrelated existing skills)
- `codex-gotify-notify.py`

`pull.py` configures the Gotify notify hook in both modes. In default API mode,
it configures and selects the Codex API provider, including when switching back
from OAuth mode. With `--oauth`, it preserves other provider selections and
profiles.

In API mode, it writes the current `CODEX_BASE_URL` value directly into `base_url` because Codex does not expand environment variables there.

Current Codex `notify` payload is completion-focused (`agent-turn-complete`), so this hook notifies when a turn completes.
Internal recap, title-generation, ACP, and auto approval turns do not notify.
If all `GOTIFY_NOTIFY_SUMMARIZER_MODEL`, `GOTIFY_NOTIFY_SUMMARIZER_ENDPOINT`, and `GOTIFY_NOTIFY_SUMMARIZER_API_KEY` are set, the hook asks the configured LLM for a one-line summary before sending to Gotify. If any one of them is missing, summarization is skipped and the preview fallback is used.

## WakaTime plugins

`pull.py` installs the WakaTime plugins through the Codex and Claude Code CLIs:

```bash
codex plugin marketplace add https://github.com/wakatime/codex-cli-wakatime.git
codex plugin add codex-cli-wakatime@wakatime

claude plugin marketplace add https://github.com/wakatime/claude-code-wakatime.git
claude plugin install claude-code-wakatime@wakatime
```

Already installed plugins are skipped, and disabled plugins remain disabled.
Three follow-ups stay manual:
- Codex plugin hooks must be approved in the next Codex session before tracking starts.
- Claude Code must be restarted to load the plugin hooks.
- The API key belongs in `~/.wakatime.cfg` (or `$WAKATIME_HOME/.wakatime.cfg`); the
  installer only warns when that file is missing and never writes it.

Both plugins manage `wakatime-cli` under `~/.wakatime/` themselves and run their
hooks through `node`, so the installer warns once when `node` is missing.

## Claude Code support

`pull.py` installs the managed Claude Code plugin into `~/.claude/skills/gotify-notify` (or `$CLAUDE_CONFIG_DIR/skills/gotify-notify`). The installer replaces only that directory and preserves `settings.json`, unrelated skills, and other plugins. Claude Code loads personal skills-directory plugins in place; no marketplace installation is required.

The plugin sends Gotify notifications for:
- main-agent response end (`Stop`)
- API failures ending a turn (`StopFailure`)
- permission prompts and MCP input dialogs (`Notification`)
- `AskUserQuestion` input requests (`PreToolUse`)

Subagent completion notifications are disabled by default, and response-end notifications are skipped while Claude reports background tasks or scheduled wakeups. Enable subagent notifications with `CLAUDE_NOTIFY_SUBAGENT=true`. Other event toggles are `CLAUDE_NOTIFY_COMPLETE`, `CLAUDE_NOTIFY_ERROR`, `CLAUDE_NOTIFY_PERMISSION`, and `CLAUDE_NOTIFY_QUESTION`; each is enabled by default.

After installing or updating the plugin, start a new Claude Code session or run `/reload-plugins`. To disable it without deleting files:

```bash
claude plugin disable gotify-notify@skills-dir
```

Credentials are read from environment variables; do not store them in repository files.

## Tokscale model aliases

`tokscale_model_alias.json` groups equivalent model IDs across OpenCode, Codex,
and OMP usage reports.

`pull.py` merges these aliases into Tokscale's `settings.json`, preserving
unrelated settings and local aliases.

The default directory is `~/.config/tokscale` on Linux/macOS and
`%APPDATA%\tokscale` on Windows. `TOKSCALE_CONFIG_DIR` overrides it; Linux also
honors `XDG_CONFIG_HOME`.

Inspect a single row per model across clients and providers:

```bash
bunx tokscale models --light --group-by model
```

Aliases affect report grouping only; model routing and pricing remain unchanged.

## oh-my-pi support

`pull.py` installs oh-my-pi config into `~/.omp/agent` (or `$OMP_AGENT_DIR`, fallback `$PI_CODING_AGENT_DIR`):
- `omp_config.yml` -> `config.yml`
- `omp_models.yaml` -> `models.yml` in API mode
- `omp_models_oauth.yaml` -> `models.yml` in OAuth mode
- `omp-gotify-notify.js` -> `extensions/omp-gotify-notify.js`

Default API mode needs `CODEX_BASE_URL`; the installer writes it into `models.yml`.

With `--oauth`, the installer writes `omp_models_oauth.yaml` to `models.yml` and
changes all `codex_api/` model role prefixes to `openai-codex/` in `config.yml`.
Both model configurations set a 272K context window for Sol/Luna and keep 128K
max output. In OAuth mode, other model metadata comes from OMP's native catalog.

The installer replaces `config.yml` with the selected rendering of `omp_config.yml`. After making machine-local changes through oh-my-pi setup, update the repository template before running `pull.py` if those changes should be preserved.

`omp-gotify-notify.js` is an oh-my-pi extension (built on official extension events), and can send Gotify notifications for:
- terminal completion or error (`agent_end`, ignores automatic continuations and aborted turns)
- ask tool waiting for input (`tool_execution_start` with `ask`)

The Gotify extension is the only OMP notification channel in this configuration.
Delivery diagnostics are written to `~/.omp/logs/gotify-notify.log`.
