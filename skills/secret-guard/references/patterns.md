# Secret Pattern Catalog

Patterns used by `scripts/scan_secrets.py`. Extend by editing the `CONTENT_PATTERNS` and `SENSITIVE_FILES` lists in the script.

## Sensitive File Patterns

| Pattern | Example Files |
|---------|---------------|
| `.env`, `.env.*` (excludes .example/.sample/.template/.dist) | .env, .env.local, .env.production |
| `*.pem`, `*.key`, `*.p12`, `*.pfx` | server.pem, tls.key, cert.p12 |
| `*.jks`, `*.keystore` | Java keystores |
| `credentials.json`, `service_account*.json` | GCP service accounts |
| `.htpasswd`, `.netrc`, `.pgpass` | Server auth files |
| `id_rsa`, `id_ed25519`, `id_ecdsa`, `id_dsa` | SSH private keys |
| `*.secret`, `token.json` | Generic secrets |
| `secrets.yml`, `secrets.yaml`, `vault.yml` | Ansible vault, config |
| `.boto`, `.s3cfg` | AWS/S3 config |
| `kubeconfig` | Kubernetes auth |
| `firebase*.json` | Firebase config |

## Content Patterns by Provider

### Cloud Providers

| Label | Pattern | Example |
|-------|---------|---------|
| AWS Access Key | `AKIA[0-9A-Z]{16}` | AKIAIOSFODNN7EXAMPLE |
| AWS Temporary Access Key | `ASIA[0-9A-Z]{16}` | ASIAIOSFODNN7EXAMPLE (STS) |
| AWS Secret Key | `(aws_secret_access_key\|AWS_SECRET_ACCESS_KEY)\s*[=:]\s*["']?[A-Za-z0-9/+=]{40}` | aws_secret_access_key = "wJalr..." |
| GCP API Key | `AIza[0-9A-Za-z_-]{35}` | AIzaSyA1234567890abcdefghijklmnop |
| Azure Storage Key | Context-gated: requires `AccountKey`/`AZURE_STORAGE_KEY` prefix + `[A-Za-z0-9+/]{86}==` | AccountKey=... |

### Code Hosting / CI

| Label | Pattern | Example |
|-------|---------|---------|
| GitHub Token (classic) | `ghp_[A-Za-z0-9]{36}` | ghp_abc123... |
| GitHub Token (fine-grained) | `github_pat_[A-Za-z0-9_]{22,}` | github_pat_11AAA... |
| GitHub OAuth | `gho_[A-Za-z0-9]{36}` | |
| GitHub App | `ghu_[A-Za-z0-9]{36}` | |
| GitHub App Install | `ghs_[A-Za-z0-9]{36}` | |
| GitHub Refresh | `ghr_[A-Za-z0-9]{36}` | |
| GitLab Token | `glpat-[A-Za-z0-9_-]{20,}` | glpat-xxxxxxxxxxxx |
| npm Token | `npm_[A-Za-z0-9]{36}` | |
| PyPI Token | `pypi-[A-Za-z0-9_-]{50,}` | |

### SaaS / Messaging

| Label | Pattern | Example |
|-------|---------|---------|
| Slack Bot Token | `xoxb-[0-9]{10,}-[0-9]{10,}-[A-Za-z0-9]{24}` | |
| Slack User Token | `xoxp-[0-9]{10,}-...-[a-f0-9]{32}` | |
| Slack Webhook | `hooks.slack.com/services/T.../B.../...` | |
| Stripe Secret Key | `sk_live_[A-Za-z0-9]{24,}` | |
| Stripe Restricted Key | `rk_live_[A-Za-z0-9]{24,}` | |
| Twilio API Key | `SK[a-f0-9]{32}` | |
| SendGrid API Key | `SG\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}` | |
| Discord Bot Token | `[MN][A-Za-z0-9]{23,}\.....\....` | |
| Telegram Bot Token | `[0-9]{8,}:AA[A-Za-z0-9_-]{33}` | |

### AI Providers

| Label | Pattern | Example |
|-------|---------|---------|
| OpenAI API Key (legacy) | `sk-[A-Za-z0-9]{20}T3BlbkFJ[A-Za-z0-9]{20}` | |
| OpenAI API Key (project) | `sk-proj-[A-Za-z0-9_-]{40,}` | sk-proj-abcdef... |
| Anthropic API Key | `sk-ant-[A-Za-z0-9_-]{80,}` | |

### Crypto / Auth

| Label | Pattern | Example |
|-------|---------|---------|
| RSA Private Key | `-----BEGIN RSA PRIVATE KEY-----` | PEM block header |
| EC Private Key | `-----BEGIN EC PRIVATE KEY-----` | |
| OpenSSH Private Key | `-----BEGIN OPENSSH PRIVATE KEY-----` | |
| Generic Private Key | `-----BEGIN PRIVATE KEY-----` | |
| PGP Private Key | `-----BEGIN PGP PRIVATE KEY BLOCK-----` | |
| JWT Token | `eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}` | eyJhbGci... |

### Generic / Heuristic

| Label | Pattern | Example |
|-------|---------|---------|
| Database URL | `(postgres\|mysql\|mongodb\|redis\|amqp\|mssql)://[^\s]{10,}` | postgres://user:pass@host/db |
| Password Assignment | `(password\|passwd\|pwd)\s*[=:]\s*\S{8,}` | password = "hunter2" |
| Secret Assignment | `(secret\|token\|api_key\|apikey\|api[-_]?secret)\s*[=:]\s*\S{8,}` | api_key = "abc123..." |
| Authorization Header | `Authorization:\s*(Bearer\|Basic\|Token)\s+[A-Za-z0-9_.+/=-]{20,}` | |
| Heroku API Key | Context-gated: requires `HEROKU_API_KEY` prefix + UUID | HEROKU_API_KEY=12345678-... |
| Doppler Token | `dp\.st\.[A-Za-z0-9_-]{40,}` | |
| Cloudflare API Token | `v1\.[A-Za-z0-9_-]{40,}` | |

## Adding Custom Patterns

Edit `scripts/scan_secrets.py`:

- **File patterns**: add to the `SENSITIVE_FILES` list (Python regex strings)
- **Content patterns**: add to `CONTENT_PATTERNS` as a `("Label", r"regex")` tuple
