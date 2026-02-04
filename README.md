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
- `GITHUB_PERSONAL_ACCESS_TOKEN` (used for github MCP)

Optional environment variables:
- `GOTIFY_URL` (used for gotify notifications)
- `GOTIFY_TOKEN_FOR_OPENCODE` (used for gotify notifications)
