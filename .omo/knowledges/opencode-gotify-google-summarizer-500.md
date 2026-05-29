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
