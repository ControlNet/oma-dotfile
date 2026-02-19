# oma-dotfile

My opencode configurations.

Linux/Mac:
```bash
curl -fsSL https://raw.githubusercontent.com/ControlNet/oma-dotfile/master/pull.py | python3
```

Windows (PowerShell):
```powershell
(Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/ControlNet/oma-dotfile/master/pull.py' -UseBasicParsing).Content | python
```

Required environment variables:
- `CODEX_BASE_URL` (with `/v1`)
- `CODEX_API_KEY`
- `ANTHROPIC_BASE_URL` (without `/v1`)
- `ANTHROPIC_AUTH_TOKEN`
- `AZURE_OPENAI_API_KEY`
- `AZURE_OPENAI_BASE_URL` (with `/openai/v1`)
- `GITHUB_PERSONAL_ACCESS_TOKEN` (used for gh tools)

Optional environment variables:
- `GOTIFY_URL` (used for gotify notifications)
- `GOTIFY_TOKEN_FOR_OPENCODE` (used for gotify notifications)
  - `GOTIFY_TOKEN_FOR_CODEX` (optional; if missing, Codex notify falls back to `GOTIFY_TOKEN_FOR_OPENCODE`)
  - `GOTIFY_TOKEN_FOR_OMP` (optional; if missing, OMP notify falls back to `GOTIFY_TOKEN_FOR_OPENCODE`/`GOTIFY_TOKEN_FOR_CODEX`)
- `GOTIFY_NOTIFY_SUMMARIZER_MODEL` (e.g., `gpt-5-nano`)
- `GOTIFY_NOTIFY_SUMMARIZER_ENDPOINT` (OpenAI-compatible endpoint, e.g., `https://api.openai.com/v1`)
- `GOTIFY_NOTIFY_SUMMARIZER_API_KEY` (API key used by summarizer requests)
- `SETUP_NOTIFY_HOOKS=0` (optional; disable auto-configure Codex notify hook during `pull.py`; default is enabled)
- `SETUP_NOTIFY_HOOKS_FORCE=1` (optional; replace existing `notify = ...` in Codex `config.toml`; default is disabled)

Codex notify hook execution logs are written to:
- `~/.codex/log/gotify-notify.log`

## Codex support

`pull.py` installs shared Codex assets into `~/.codex` (or `$CODEX_DIR` if set):
- `AGENTS.md`
- `skills/` (merge-copy, preserves unrelated existing skills)
- `codex-gotify-notify.py`

Enable Gotify notification in `~/.codex/config.toml`:

```toml
notify = ["python3", "/absolute/path/to/.codex/codex-gotify-notify.py"]
```

Or let `pull.py` auto-configure it:

```bash
SETUP_NOTIFY_HOOKS=1 python3 pull.py
```

Current Codex `notify` payload is completion-focused (`agent-turn-complete`), so this hook notifies when a turn completes.
If all `GOTIFY_NOTIFY_SUMMARIZER_MODEL`, `GOTIFY_NOTIFY_SUMMARIZER_ENDPOINT`, and `GOTIFY_NOTIFY_SUMMARIZER_API_KEY` are set, the hook asks the configured LLM for a one-line summary before sending to Gotify. If any one of them is missing, summarization is skipped and the preview fallback is used.

## oh-my-pi support

`pull.py` installs oh-my-pi config into `~/.omp/agent` (or `$OMP_AGENT_DIR`, fallback `$PI_CODING_AGENT_DIR`):
- `omp_config.yml` -> `config.yml`
- `omp_models.yaml` -> `models.yml`
- `omp-gotify-notify.js` -> `extensions/omp-gotify-notify.js`

Before writing `models.yml`, installer replaces `baseUrl: CODEX_BASE_URL` with the real value from `CODEX_BASE_URL`.
This is required because oh-my-pi does not auto-expand environment variables for `baseUrl`.
If `CODEX_BASE_URL` is missing, the placeholder remains and installer prints a warning.

`omp-gotify-notify.js` is an oh-my-pi extension (built on official extension events), and can send Gotify notifications for:
- turn completion (`turn_end`)
- retry failure (`auto_retry_end`)
- ask tool waiting for input (`tool_call` with `ask`)
