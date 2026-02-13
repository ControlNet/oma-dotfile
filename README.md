# omo-dotfile

My opencode configurations.

Linux/Mac:
```bash
curl -fsSL https://raw.githubusercontent.com/ControlNet/omo-dotfile/master/pull.py | python3
```

Windows (PowerShell):
```powershell
(Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/ControlNet/omo-dotfile/master/pull.py' -UseBasicParsing).Content | python
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
  - `GOTIFY_TOKEN_FOR_CLAUDE_CODE` (optional; if missing, Claude notify falls back to `GOTIFY_TOKEN_FOR_OPENCODE`)
- `OPENCODE_GOTIFY_NOTIFY_SUMMARIZER` (format: "provider/model", e.g., "azure-openai/gpt-5-nano")
  - `CODEX_GOTIFY_NOTIFY_SUMMARIZER` (format: "provider/model", supports `anthropic`, `openai` and `azure-openai`; falls back to `OPENCODE_GOTIFY_NOTIFY_SUMMARIZER`)
  - `CLAUDE_GOTIFY_NOTIFY_SUMMARIZER` (format: "provider/model", supports `anthropic`, `openai`, `azure-openai`; falls back to `OPENCODE_GOTIFY_NOTIFY_SUMMARIZER`)
- `SETUP_NOTIFY_HOOKS=0` (optional; disable auto-configure Codex/Claude notify hooks during `pull.py`; default is enabled)
- `SETUP_NOTIFY_HOOKS_FORCE=1` (optional; replace existing `notify = ...` in Codex `config.toml`; default is disabled)

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
If `CODEX_GOTIFY_NOTIFY_SUMMARIZER` (or `OPENCODE_GOTIFY_NOTIFY_SUMMARIZER`) is set, the hook asks the configured LLM for a one-line summary before sending to Gotify. Supported providers: `anthropic`, `openai`, `azure-openai`.

## Claude Code support

`pull.py` installs shared Claude assets into `~/.claude` (or `$CLAUDE_DIR` if set):
- `CLAUDE.md` (from `_AGENTS.md`, for Claude-native instruction loading)
- `skills/` (merge-copy, preserves unrelated existing skills)
- `claude-gotify-notify.py`

Enable hooks in `~/.claude/settings.json`:

Or let `pull.py` auto-merge the hook entries into `~/.claude/settings.json`:

```bash
SETUP_NOTIFY_HOOKS=1 python3 pull.py
```
