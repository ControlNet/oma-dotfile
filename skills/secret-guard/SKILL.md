---
name: secret-guard
description: >
  Detect secrets and credentials before they leak into git. Use this skill when:
  (1) About to commit code — scan staged files for API keys, tokens, passwords, private keys
  (2) User mentions secrets, credentials, API keys, tokens, .env, or sensitive data
  (3) User asks to "check secrets", "audit security", "review for leaks"
  (4) User asks about .gitignore coverage for sensitive files
  (5) Before creating a PR or push — final safety check
  Trigger phrases: "check for secrets", "scan for leaks", "is this safe to commit",
  "audit .gitignore", "any credentials exposed", "secrets", "confidential".
---

# Secret Guard

Prevent secret leakage via git. Cross-platform, Python stdlib only (no pip install).

## Pre-Commit Check (DEFAULT)

Run before ANY commit that touches config, env, auth, or infra files:

```
python scripts/scan_secrets.py staged
```

Exit 0 = clean, exit 1 = findings. If findings exist, **do NOT commit** — remove or move secrets to env vars first.

## Full Repo Audit

Scan all tracked files:

```
python scripts/scan_secrets.py tracked
```

## Gitignore Coverage Audit

Verify .gitignore covers common sensitive file patterns:

```
python scripts/scan_secrets.py gitignore
```

Reports which patterns (.env, *.pem, *.key, credentials.json, etc.) are NOT covered.

## When User Mentions Secrets/Credentials

If the user discusses API keys, tokens, passwords, or sensitive config:

1. Run `python scripts/scan_secrets.py staged` to check if anything sensitive is staged
2. Run `python scripts/scan_secrets.py gitignore` to verify .gitignore coverage
3. If findings: list them clearly with remediation steps
4. If clean: confirm no secrets detected

## Remediation Workflow

When secrets are found:

1. **Unstage the file**: `git reset HEAD <file>`
2. **Move secret to env var**: replace hardcoded value with `os.environ["KEY"]` / `process.env.KEY` etc.
3. **Add to .gitignore** if the file is inherently sensitive (.env, *.pem, credentials.json)
4. **If already committed**: warn the user that the secret is in git history and suggest `git filter-repo` or rotating the credential
5. Re-scan: `python scripts/scan_secrets.py staged`

## What Gets Detected

- **Sensitive files**: .env, *.pem, *.key, *.p12, credentials.json, id_rsa, kubeconfig, etc.
- **Content patterns**: AWS keys (AKIA...), GitHub tokens (ghp_/github_pat_), GCP API keys, Stripe keys, Slack tokens, private key blocks (-----BEGIN ... PRIVATE KEY-----), JWT tokens, database connection strings, password/secret variable assignments, and 30+ provider-specific patterns
- **Gitignore gaps**: checks whether common sensitive file types are covered by .gitignore rules

For the full pattern catalog, see [references/patterns.md](references/patterns.md).
