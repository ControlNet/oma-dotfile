# OpenCode Gotify Google Summarizer 500

Remote OpenCode notifier diagnostics showed repeated failures in the summarizer
step, not in Gotify delivery:

- Log path: `~/.local/share/opencode/gotify-notify.log`
- Scope: `[gotify] summarizer chat/completions HTTP 500 Internal Server Error`
- Endpoint family: `https://generativelanguage.googleapis.com/v1beta/openai/`
- Model observed: `gemma-4-31b-it`
- Error body: Google `INTERNAL` / `Internal error encountered.`
- No matching `[gotify] delivery` errors were found, so Gotify `/message` was
  not the failing request.

This is distinct from OpenCode upstream model-call failures such as
`AI_APICallError` against `llm.neuro-x.cloud.edu.au/v1/responses`.

Mitigation in `plugins/gotify-notify.js`:

1. Try the existing OpenAI-compatible `/chat/completions` request first.
2. If that fails and the endpoint is Google AI Studio, fallback to direct Gemini
   `models/{model}:generateContent` with `x-goog-api-key`.
3. Keep skipping OpenAI `/responses` by default for Google endpoints, because
   the Google compatibility endpoint does not reliably support it.

Verification command used:

```bash
node --check plugins/gotify-notify.js
```

A local Node fixture also mocked:

- `/chat/completions` returning HTTP 500
- `:generateContent` returning a candidate text
- Gotify `/message` receiving the fallback summary

and confirmed `opencode google generateContent fallback: ok`.

## Codex notifier recurrence

Remote Codex diagnostics on `ansr-5090-4` showed the same provider-family
failure in `~/.codex/log/gotify-notify.log`:

- `summarizer_start model=gemma-4-31b-it endpoint=https://generativelanguage.googleapis.com/v1beta/openai`
- `summarizer_fallback route=responses reason=chat_completions_failed_or_empty`
- `http_error url=https://generativelanguage.googleapis.com/v1beta/openai/responses status=404`
- `summarizer_failed fallback=preview`

This means Gotify delivery still succeeds for most events, but Codex falls back
to the raw preview because the Python notifier did not yet have the Google
direct Gemini fallback. The Codex fix mirrors the OpenCode fix:

1. Try OpenAI-compatible `/chat/completions`.
2. For Google AI Studio endpoints, fallback to
   `/v1beta/models/{model}:generateContent` with `x-goog-api-key`.
3. Skip `/responses` for Google endpoints; keep `/responses` only for generic
   non-Google OpenAI-compatible providers.

Verification used a local inline `importlib` fixture that monkeypatched
`_json_post`, asserted the Google fallback reached `:generateContent` without
calling `/responses`, asserted non-Google providers still used `/responses`,
and then compiled the script:

```bash
python3 -m py_compile codex-gotify-notify.py
```
