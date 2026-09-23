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

OAuth mode changes model routing for Codex, OpenCode/OMO, and OMP. Existing
Codex/OpenCode custom provider settings and OMO reasoning levels are retained.
It does not require `CODEX_BASE_URL` or `CODEX_API_TOKEN`. Sign in separately:

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

OMO follows OpenCode detection; Tokscale is detected by its configuration directory.

To install everything regardless of detection, for example to pre-seed a machine before
installing the agents:

```bash
python3 pull.py --all
curl -fsSL https://raw.githubusercontent.com/ControlNet/oma-dotfile/master/pull.py | python3 - --all
```

## Environment variables

Recommended:
- `OPENCODE_DISABLE_CLAUDE_CODE=1` (disable claude-code support for opencode)

Third-party API mode:
- `CODEX_BASE_URL` (include `/v1`)
- `CODEX_API_TOKEN`

Optional integrations:
- `GITHUB_PERSONAL_ACCESS_TOKEN` (used for gh tools)
- `NOTION_API_TOKEN` (used by the notion-api skill for Notion REST API calls)
- `GOTIFY_URL` (used for gotify notifications)
- `GOTIFY_TOKEN_FOR_OPENCODE` (used for gotify notifications)
  - `GOTIFY_TOKEN_FOR_CODEX` (optional; if missing, Codex notify falls back to `GOTIFY_TOKEN_FOR_OPENCODE`)
  - `GOTIFY_TOKEN_FOR_OMP` (optional; if missing, OMP notify falls back to `GOTIFY_TOKEN_FOR_OPENCODE`/`GOTIFY_TOKEN_FOR_CODEX`)
  - `GOTIFY_TOKEN_FOR_CLAUDE` (optional; if missing, Claude Code notify falls back to the other Gotify tokens)
- `OPENCODE_NOTIFY_TITLE`, `CODEX_NOTIFY_TITLE`, `OMP_NOTIFY_TITLE`, `CLAUDE_NOTIFY_TITLE` (optional; override the default Gotify title format `<Agent> :: <project>@<hostname>`)
- `GOTIFY_NOTIFY_SUMMARIZER_MODEL` (e.g., `gpt-5-nano`)
- `GOTIFY_NOTIFY_SUMMARIZER_ENDPOINT` (OpenAI-compatible endpoint, e.g., `https://api.openai.com/v1`)
- `GOTIFY_NOTIFY_SUMMARIZER_API_KEY` (API key used by summarizer requests)

Keep credentials out of this repository. If using `.env.local`, add it to `.gitignore`.

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
Obsolete OMO configuration files are renamed to backups during installation.

## Codex support

`pull.py` installs shared Codex assets into `~/.codex` (or `$CODEX_DIR` if set):
- `AGENTS.md`
- `skills/` (merge-copy, preserves unrelated existing skills)
- `codex-gotify-notify.py`

`pull.py` configures the Gotify notify hook in both modes. In default API mode,
it configures and selects the Codex API provider, including when switching back
from OAuth mode. With `--oauth`, it preserves other provider selections and
profiles.

The hook notifies completed turns and skips internal recap, title-generation,
ACP, and auto approval turns. Set all three Gotify summarizer variables above
to receive one-line summaries; otherwise notifications use a preview.

## WakaTime plugins

`pull.py` installs the WakaTime plugins through the Codex and Claude Code CLIs.

Already installed plugins are skipped, and disabled plugins remain disabled.
Three follow-ups stay manual:
- Codex plugin hooks must be approved in the next Codex session before tracking starts.
- Claude Code must be restarted to load the plugin hooks.
- The API key belongs in `~/.wakatime.cfg` (or `$WAKATIME_HOME/.wakatime.cfg`); the
  installer only warns when that file is missing and never writes it.

Both plugins require Node.js.

## Claude Code support

`pull.py` installs the managed Claude Code plugin into `~/.claude/skills/gotify-notify` (or `$CLAUDE_CONFIG_DIR/skills/gotify-notify`). It preserves `settings.json`, unrelated skills, and other plugins.

The plugin notifies for completed turns, errors, permission prompts, and
requests for user input.

Subagent notifications are disabled by default; enable them with
`CLAUDE_NOTIFY_SUBAGENT=true`.

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

`pull.py` installs configuration, models, and the Gotify extension into
`~/.omp/agent` (or `$OMP_AGENT_DIR`, fallback `$PI_CODING_AGENT_DIR`).
Default API mode needs `CODEX_BASE_URL`.

With `--oauth`, OMP uses native `openai-codex` models. Both modes set a 272K
context window for Sol/Luna and keep 128K max output.

The installer replaces `config.yml` on updates. Copy local oh-my-pi setup changes
back to `omp_config.yml` if you want to keep them.

The Gotify extension notifies when a turn completes, fails, or needs user input.

The Gotify extension is the only OMP notification channel in this configuration.
Delivery diagnostics are written to `~/.omp/logs/gotify-notify.log`.
