# Claude Code Gotify Summarizer Timeout

On 2026-10-13, Claude Code Gotify notifications fell back to the raw preview
while Codex summaries using the same summarizer settings kept working.

Symptoms in `~/.claude/logs/gotify-notify.log`:

- `summarizer_chat TimeoutError` (sometimes `HTTP_503`)
- followed by `summarizer_responses HTTP_404`

Environment at the time:

- `GOTIFY_NOTIFY_SUMMARIZER_ENDPOINT=https://generativelanguage.googleapis.com/v1beta/openai/`
- `GOTIFY_NOTIFY_SUMMARIZER_MODEL=gemini-3.5-flash-lite`

Root causes in `claude-plugins/gotify-notify/scripts/notify.py`:

1. `CLAUDE_NOTIFY_SUMMARIZER_TIMEOUT_SEC` defaults to 8 and is clamped to
   `maximum=8`, so the env var cannot raise it. Measured `/chat/completions`
   latency on this endpoint was 42-90+ s; Codex logs showed 12-86 s successes
   with Codex's 120 s default (`CODEX_NOTIFY_SUMMARIZER_TIMEOUT_SEC`).
2. After chat fails, the Claude notifier tries `/responses`, which the Google
   OpenAI-compatible endpoint does not serve (404). It lacks the Google
   `models/{model}:generateContent` fallback that the OpenCode and Codex
   notifiers have (see `opencode-gotify-google-summarizer-500.md`).

The hooks are `async: true`, and background async hooks do not enforce the
hook timeout (see `claude-code-gotify-design-investigation.md`), so a longer
script-side summarizer deadline does not block the Claude Code session.

Latency check (does not print the key):

```bash
curl -sS -o /dev/null -w "HTTP %{http_code} in %{time_total}s\n" --max-time 90 \
  "${GOTIFY_NOTIFY_SUMMARIZER_ENDPOINT%/}/chat/completions" \
  -H "Authorization: Bearer $GOTIFY_NOTIFY_SUMMARIZER_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"$GOTIFY_NOTIFY_SUMMARIZER_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Say hi\"}],\"max_tokens\":20}"
```

## Fix

`CLAUDE_NOTIFY_SUMMARIZER_TIMEOUT_SEC` now defaults to
`DEFAULT_SUMMARIZER_TIMEOUT_SEC = 120` (matching Codex) with no upper clamp.
Covered by `test_summary_timeout_matches_codex_default_and_allows_override`.
The Google `generateContent` fallback is still not ported to the Claude
notifier; a chat failure still falls through to `/responses` (404 on Google).

`pull.py` syncs from GitHub, so unpushed local changes must be copied to
`~/.claude/skills/gotify-notify/scripts/notify.py` manually for local testing.
