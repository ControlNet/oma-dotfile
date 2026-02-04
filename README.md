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
- `ANTHROPIC_BASE_URL` (without `/v1`)
- `ANTHROPIC_AUTH_TOKEN`
- `AZURE_OPENAI_API_KEY`
- `AZURE_OPENAI_BASE_URL` (with `/openai/v1`)
- `GITHUB_PERSONAL_ACCESS_TOKEN` (used for gh tools)

Optional environment variables:
- `GOTIFY_URL` (used for gotify notifications)
- `GOTIFY_TOKEN_FOR_OPENCODE` (used for gotify notifications)
- `OPENCODE_GOTIFY_NOTIFY_SUMMARIZER` (format: "provider/model", e.g., "azure-openai/gpt-5-nano")
