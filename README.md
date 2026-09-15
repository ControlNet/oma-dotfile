# oma-dotfile

My opencode configurations.

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

For a streamed installer, pass arguments after `-` (once the updated script is
published to the selected remote revision):

```bash
curl -fsSL https://raw.githubusercontent.com/ControlNet/oma-dotfile/master/pull.py | python3 - --oauth
```

Windows (PowerShell):

```powershell
(Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/ControlNet/oma-dotfile/master/pull.py' -UseBasicParsing).Content | python - --oauth
```

- Codex: comment an existing top-level `model_provider = "codex_api"` assignment.
  If absent, add nothing. Preserve custom provider definitions, other provider
  selections, and profiles. With no overriding selection, Codex uses `openai`.
- OpenCode: preserve the existing `provider.codex` object, or leave it absent if
  not configured. Other settings still sync from the template. OAuth rendering
  accepts JSONC input and writes formatted JSON; comments are not retained in
  this file. Legacy `opencode.json` provider settings are carried forward before
  the existing installer retires that file to a backup.
- OMO: replace `codex/` model prefixes with `openai/` in the installed
  `~/.omo/omo.jsonc`, retaining model IDs and reasoning settings.
- OMP: switch `codex_api/` selectors to `openai-codex/` and install
  `providers: {}` in `models.yml` to use the native model catalog.

OAuth mode does not require `CODEX_BASE_URL` or `CODEX_API_KEY`. It changes routing,
not credentials: log in through each agent, and verify that the retained model
IDs and reasoning levels are available to your account.

```bash
codex login
codex login status
opencode auth login --provider openai
omp
```

In OpenCode choose ChatGPT authentication. Inside OMP run `/login openai-codex`.
Existing explicit model selections, profiles, project overrides, and resumed
sessions can override defaults. The Gotify summarizer uses its own configuration.
OAuth mode neither forces a login method nor copies or rewrites credentials.

To restore the third-party configuration, run the installer without `--oauth`
with the gateway environment variables configured:

```bash
python3 pull.py
```

The mode is not persisted: each ordinary installation restores API routing.
Existing backup settings apply. The installer always clones `REPO_REV` from GitHub,
so local template changes are not used until available in that remote revision.

Verification uses Python's standard library and synthetic configurations in
temporary directories; it does not install into the real home directory:

```bash
python3 -m unittest discover -s tests -p 'test_pull_oauth.py'
git diff --check
```

Expected: all OAuth installer tests pass and the diff check reports no whitespace errors.

## Environment variables

Recommended environment variables:
- `OPENCODE_DISABLE_CLAUDE_CODE=1` (disable claude-code support for opencode)

Optional environment variables:
- `CODEX_BASE_URL` (with `/v1`, required for the third-party API provider; not required by `--oauth`)
- `CODEX_API_KEY` (required for the third-party API provider; not required by `--oauth`)
- `GITHUB_PERSONAL_ACCESS_TOKEN` (used for gh tools)
- `NOTION_API_TOKEN` (used by the notion-api skill for Notion REST API calls)

Other optional environment variables:
- `GOTIFY_URL` (used for gotify notifications)
- `GOTIFY_TOKEN_FOR_OPENCODE` (used for gotify notifications)
  - `GOTIFY_TOKEN_FOR_CODEX` (optional; if missing, Codex notify falls back to `GOTIFY_TOKEN_FOR_OPENCODE`)
  - `GOTIFY_TOKEN_FOR_OMP` (optional; if missing, OMP notify falls back to `GOTIFY_TOKEN_FOR_OPENCODE`/`GOTIFY_TOKEN_FOR_CODEX`)
- `OPENCODE_NOTIFY_TITLE`, `CODEX_NOTIFY_TITLE`, `OMP_NOTIFY_TITLE` (optional; override the default Gotify title format `<Agent> :: <project>@<hostname>`)
- `GOTIFY_NOTIFY_SUMMARIZER_MODEL` (e.g., `gpt-5-nano`)
- `GOTIFY_NOTIFY_SUMMARIZER_ENDPOINT` (OpenAI-compatible endpoint, e.g., `https://api.openai.com/v1`)
- `GOTIFY_NOTIFY_SUMMARIZER_API_KEY` (API key used by summarizer requests)

Codex notify hook execution logs are written to:
- `~/.codex/log/gotify-notify.log`

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
it also selects and configures the Codex API provider. With `--oauth`, it only
comments an existing top-level `model_provider = "codex_api"` assignment and
preserves the provider definition; it does not add a selector if one is absent.

In API mode, it writes the current `CODEX_BASE_URL` value directly into `base_url` because Codex does not expand environment variables there.

Generated provider config in default API mode:

```toml
model_provider = "codex_api"

[model_providers.codex_api]
name = "codex_api"
base_url = "<CODEX_BASE_URL value>"
env_key = "CODEX_API_KEY"
wire_api = "responses"
```

Generated Gotify notification hook:

```toml
notify = ["python3", "/absolute/path/to/.codex/codex-gotify-notify.py"]
```

Run the installer to auto-configure these entries:

```bash
python3 pull.py
```

Current Codex `notify` payload is completion-focused (`agent-turn-complete`), so this hook notifies when a turn completes.
Hidden title-generation and Conversation recap turns (automatic and manual `/recap`) are filtered by their fixed input prompt signatures before summarization or delivery. Recap remains available in Codex; skipped recap notifications log `run_skip reason=conversation_recap`. These signatures may need updating if Codex changes its internal prompts.
Turns launched through `codex-acp` are filtered by inspecting the notify hook's ancestor process chain. Other Codex App Server clients remain eligible for notifications.
Auto approval reviewer turns are filtered out by checking payload/session metadata for `model=codex-auto-review` or approval-reviewer markers. If Codex does not write session metadata for those turns, the hook falls back to scanning recent `~/.codex/log/codex-tui.log` lines for `model=codex-auto-review`. Override that path with `CODEX_NOTIFY_TUI_LOG_FILE` if needed.
If all `GOTIFY_NOTIFY_SUMMARIZER_MODEL`, `GOTIFY_NOTIFY_SUMMARIZER_ENDPOINT`, and `GOTIFY_NOTIFY_SUMMARIZER_API_KEY` are set, the hook asks the configured LLM for a one-line summary before sending to Gotify. If any one of them is missing, summarization is skipped and the preview fallback is used.

## Tokscale model aliases

`tokscale_model_alias.json` is a flat mapping from reported model names to upstream
model IDs, such as `codex_api/gpt-6-astra` -> `gpt-6-astra` and
`azure_anthropic/claude-opus-4-6` -> `claude-opus-4-6`. It covers the current
OpenCode/Codex/OMP GPT catalog and provider-prefixed OpenAI/Anthropic model IDs
observed in local reports. OAuth display labels are omitted because OpenCode now
uses model IDs and local OMP reports already record model IDs. Unknown model identities
are not guessed; add an explicit entry when another spelling appears.

`pull.py` merges this mapping into `settings.json` under `modelAliases`. Unrelated
settings and local aliases are preserved; repository entries win for identical
keys. Existing settings are backed up unless `NO_BACKUP=1`; unchanged settings
are not rewritten. Invalid JSON or a non-object `modelAliases` is left untouched
with a warning.

The default directory is `~/.config/tokscale` on Linux/macOS and
`%APPDATA%\tokscale` on Windows. `TOKSCALE_CONFIG_DIR` overrides it; Linux also
honors `XDG_CONFIG_HOME`.

To install only the aliases from this checkout using Python 3.11+ (standard
library only):

```bash
python3 - <<'PY'
from pathlib import Path
import pull
pull.install_tokscale_model_aliases(Path.cwd(), pull.get_tokscale_config_dir(), pull.timestamp())
PY
```

Inspect a single row per model across clients and providers:

```bash
bunx tokscale models --light --group-by model
```

Aliases affect local report grouping only, preserving client/provider attribution,
pricing totals, and exported/submitted model identities. Tokscale 4.15.1 gives
OpenCode's configured `name` precedence over aliases. The repository therefore
omits model-level `name` fields in `opencode.jsonc`, allowing model IDs and aliases
to determine grouping. OpenCode's model picker also displays the IDs. Install the
updated OpenCode configuration as well as the aliases for this change to take
effect; installing only the aliases leaves existing local display names active.
See the [upstream grouping implementation](https://github.com/junhoyeo/tokscale/blob/main/crates/tokscale-core/src/lib.rs).

Verification (synthetic settings in temporary directories, no user settings changed):

```bash
python3 -m unittest discover -s tests -p 'test_tokscale_model_aliases.py'
git diff --check
```

Expected: all tests pass and no whitespace errors.

## oh-my-pi support

`pull.py` installs oh-my-pi config into `~/.omp/agent` (or `$OMP_AGENT_DIR`, fallback `$PI_CODING_AGENT_DIR`):
- `omp_config.yml` -> `config.yml`
- `omp_models.yaml` -> `models.yml`
- `omp-gotify-notify.js` -> `extensions/omp-gotify-notify.js`

The custom model provider ID is `codex_api`. The shorter `codex` ID is reserved by oh-my-pi's built-in Codex discovery integrations. The repository config also disables oh-my-pi's bundled `azure` model provider; no Azure endpoint is configured.

In default API mode, before writing `models.yml`, the installer replaces `baseUrl: CODEX_BASE_URL` with the real value from `CODEX_BASE_URL`.
This is required because oh-my-pi does not auto-expand environment variables for `baseUrl`.
If `CODEX_BASE_URL` is missing, the placeholder remains and installer prints a warning.

With `--oauth`, the installer writes `providers: {}` to `models.yml` and changes
all `codex_api/` model role prefixes to `openai-codex/` in `config.yml`.
It skips gateway URL interpolation and uses OMP's native model catalog.

The installer replaces `config.yml` with the selected rendering of `omp_config.yml`. After making machine-local changes through oh-my-pi setup, update the repository template before running `pull.py` if those changes should be preserved.

`omp-gotify-notify.js` is an oh-my-pi extension (built on official extension events), and can send Gotify notifications for:
- terminal completion or error (`agent_end`, ignores automatic continuations and aborted turns)
- ask tool waiting for input (`tool_execution_start` with `ask`)

The extension is the sole OMP notification channel in the repository config, so OMP's native completion, error, and ask notifications are disabled. Summarizer requests are capped at 8 seconds per compatible route and Gotify delivery is capped at 5 seconds, keeping worst-case network waiting to about 21 seconds within OMP's 30-second extension-handler budget. Redacted delivery diagnostics are written to `~/.omp/logs/gotify-notify.log`.
