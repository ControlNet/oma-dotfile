#!/usr/bin/env python3
"""
scan_secrets.py — Cross-platform git secret scanner (Python stdlib only)

Usage:
    python scan_secrets.py staged          Scan staged (git add) files
    python scan_secrets.py tracked         Scan all git-tracked files
    python scan_secrets.py path <dir>      Scan a specific directory
    python scan_secrets.py gitignore       Audit .gitignore coverage

Exit codes: 0 = clean, 1 = findings, 2 = usage error
"""

import os
import re
import subprocess
import sys


# ── ANSI colors (disabled when not a TTY or on dumb terminals) ───────

_COLOR = sys.stdout.isatty() and os.environ.get("TERM", "") != "dumb"

RED = "\033[0;31m" if _COLOR else ""
YELLOW = "\033[0;33m" if _COLOR else ""
GREEN = "\033[0;32m" if _COLOR else ""
CYAN = "\033[0;36m" if _COLOR else ""
BOLD = "\033[1m" if _COLOR else ""
RESET = "\033[0m" if _COLOR else ""

# ── Sensitive file patterns ──────────────────────────────────────────

SENSITIVE_FILES = [
    r"\.env$",
    r"\.env\.(?!example|sample|template|dist|test|bak)",
    r"\.pem$",
    r"\.key$",
    r"\.p12$",
    r"\.pfx$",
    r"\.jks$",
    r"\.keystore$",
    r"credentials\.json$",
    r"service[-_]?account.*\.json$",
    r"\.htpasswd$",
    r"\.netrc$",
    r"\.pgpass$",
    r"id_rsa$",
    r"id_ed25519$",
    r"id_ecdsa$",
    r"id_dsa$",
    r"\.secret$",
    r"token\.json$",
    r"secrets\.ya?ml$",
    r"vault\.ya?ml$",
    r"\.boto$",
    r"\.s3cfg$",
    r"gcloud.*credentials",
    r"firebase.*\.json$",
    r"kubeconfig$",
]

# ── Content patterns: (label, regex) ────────────────────────────────
# Tuned for high signal: require specific prefixes, formats, or entropy.

CONTENT_PATTERNS = [
    # AWS
    ("AWS Access Key", r"AKIA[0-9A-Z]{16}"),
    ("AWS Temporary Access Key", r"ASIA[0-9A-Z]{16}"),
    (
        "AWS Secret Key",
        r"""(?:aws_secret_access_key|AWS_SECRET_ACCESS_KEY)\s*[=:]\s*["']?[A-Za-z0-9/+=]{40}""",
    ),
    # GitHub
    ("GitHub Token (classic)", r"ghp_[A-Za-z0-9]{36,}"),
    ("GitHub Token (fine-grained)", r"github_pat_[A-Za-z0-9_]{22,}"),
    ("GitHub OAuth", r"gho_[A-Za-z0-9]{36}"),
    ("GitHub App", r"ghu_[A-Za-z0-9]{36}"),
    ("GitHub App Install", r"ghs_[A-Za-z0-9]{36}"),
    ("GitHub Refresh", r"ghr_[A-Za-z0-9]{36}"),
    # GitLab
    ("GitLab Token", r"glpat-[A-Za-z0-9_\-]{20,}"),
    # Slack
    ("Slack Bot Token", r"xoxb-[0-9]{10,}-[0-9]{10,}-[A-Za-z0-9]{24}"),
    ("Slack User Token", r"xoxp-[0-9]{10,}-[0-9]{10,}-[0-9]{10,}-[a-f0-9]{32}"),
    ("Slack Webhook", r"hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+"),
    # Google / GCP
    ("GCP API Key", r"AIza[0-9A-Za-z_\-]{35}"),
    (
        "GCP OAuth Client Secret",
        r"""["']client_secret["']\s*:\s*["'][A-Za-z0-9_\-]{24}["']""",
    ),
    # Stripe
    ("Stripe Secret Key", r"sk_live_[A-Za-z0-9]{24,}"),
    ("Stripe Restricted Key", r"rk_live_[A-Za-z0-9]{24,}"),
    # Twilio
    ("Twilio API Key", r"SK[a-f0-9]{32}"),
    # SendGrid
    ("SendGrid API Key", r"SG\.[A-Za-z0-9_\-]{22}\.[A-Za-z0-9_\-]{43}"),
    # Private keys
    ("RSA Private Key", r"-----BEGIN RSA PRIVATE KEY-----"),
    ("EC Private Key", r"-----BEGIN EC PRIVATE KEY-----"),
    ("DSA Private Key", r"-----BEGIN DSA PRIVATE KEY-----"),
    ("OpenSSH Private Key", r"-----BEGIN OPENSSH PRIVATE KEY-----"),
    ("PGP Private Key", r"-----BEGIN PGP PRIVATE KEY BLOCK-----"),
    ("Generic Private Key", r"-----BEGIN PRIVATE KEY-----"),
    # JWT
    ("JWT Token", r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
    # Database connection strings
    ("Database URL", r"(?:postgres|mysql|mongodb|redis|amqp|mssql)://[^\s'\"]{10,}"),
    # Generic assignments
    (
        "Password Assignment",
        r"""(?:password|passwd|pwd)\s*[=:]\s*["'][^\s"']{8,}["']""",
    ),
    (
        "Secret Assignment",
        r"""(?:secret|token|api_key|apikey|api[-_]?secret)\s*[=:]\s*["'][^\s"']{8,}["']""",
    ),
    (
        "Authorization Header",
        r"Authorization:\s*(?:Bearer|Basic|Token)\s+[A-Za-z0-9_.+/=\-]{20,}",
    ),
    # Heroku (require HEROKU context to avoid UUID false positives)
    (
        "Heroku API Key",
        r"(?i)(?:heroku[_\s]*api[_\s]*key|HEROKU_API_KEY)\s*[=:]\s*[\"']?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    ),
    # npm / PyPI
    ("npm Token", r"npm_[A-Za-z0-9]{36}"),
    ("PyPI Token", r"pypi-[A-Za-z0-9_\-]{50,}"),
    # Cloudflare
    ("Cloudflare API Token", r"v1\.[A-Za-z0-9_\-]{40,}"),
    # Discord / Telegram
    (
        "Discord Bot Token",
        r"[MN][A-Za-z0-9]{23,}\.[A-Za-z0-9_\-]{6}\.[A-Za-z0-9_\-]{27,}",
    ),
    ("Telegram Bot Token", r"[0-9]{8,}:AA[A-Za-z0-9_\-]{33}"),
    # Azure (require storage context to avoid generic base64 false positives)
    (
        "Azure Storage Key",
        r"(?i)(?:AccountKey|AZURE[_\s]*STORAGE[_\s]*KEY|azure[_\s]*storage[_\s]*connection)\s*[=:]\s*[\"']?[A-Za-z0-9+/]{86}==",
    ),
    # Doppler
    ("Doppler Token", r"dp\.st\.[A-Za-z0-9_\-]{40,}"),
    # AI providers
    ("OpenAI API Key (legacy)", r"sk-[A-Za-z0-9]{20}T3BlbkFJ[A-Za-z0-9]{20}"),
    ("OpenAI API Key (project)", r"sk-proj-[A-Za-z0-9_\-]{40,}"),
    ("Anthropic API Key", r"sk-ant-[A-Za-z0-9_\-]{80,}"),
]

# Pre-compile for performance
_COMPILED_FILE_PATTERNS = [re.compile(p, re.IGNORECASE) for p in SENSITIVE_FILES]
_COMPILED_CONTENT = [(label, re.compile(pat)) for label, pat in CONTENT_PATTERNS]

# ── Gitignore audit patterns ────────────────────────────────────────

GITIGNORE_CHECK = [
    ".env",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "credentials.json",
    "*.jks",
    "*.keystore",
    ".htpasswd",
    ".netrc",
    ".pgpass",
    "id_rsa",
    "id_ed25519",
    "*.secret",
    "token.json",
    "secrets.yml",
    "secrets.yaml",
    ".boto",
    ".s3cfg",
    "kubeconfig",
]


def git(*args: str) -> tuple[int, str]:
    try:
        r = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return r.returncode, r.stdout.strip()
    except FileNotFoundError:
        print(f"{RED}Error: git not found in PATH{RESET}", file=sys.stderr)
        sys.exit(2)
    except subprocess.TimeoutExpired:
        return 1, ""


def get_files(mode: str, target: str) -> list[str]:
    if mode == "staged":
        rc, out = git("diff", "--cached", "--name-only", "--diff-filter=ACMR")
    elif mode == "tracked":
        rc, out = git("ls-files")
    elif mode == "path":
        if not target:
            print(
                f"{RED}Error: 'path' mode requires a directory argument{RESET}",
                file=sys.stderr,
            )
            sys.exit(2)
        files = []
        for root, _dirs, filenames in os.walk(target):
            if ".git" in root.split(os.sep):
                continue
            for f in filenames:
                files.append(os.path.join(root, f))
        return files
    else:
        print(
            f"{RED}Usage: {sys.argv[0]} {{staged|tracked|path <dir>|gitignore}}{RESET}",
            file=sys.stderr,
        )
        sys.exit(2)
    if rc != 0:
        print(f"{RED}Error: git command failed (exit {rc}){RESET}", file=sys.stderr)
        sys.exit(2)
    if not out:
        return []
    return out.splitlines()


def is_binary(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            chunk = f.read(8192)
        return b"\x00" in chunk
    except OSError:
        return True


def redact(s: str) -> str:
    if len(s) > 20:
        return s[:12] + "…" + s[-4:]
    return s[:8] + "…"


# ── Scanners ─────────────────────────────────────────────────────────


def scan_filenames(files: list[str]) -> int:
    found = 0
    for filepath in files:
        for pat in _COMPILED_FILE_PATTERNS:
            if pat.search(filepath):
                if found == 0:
                    print(f"\n{BOLD}{RED}▸ Sensitive files detected:{RESET}")
                print(
                    f"  {RED}✗{RESET} {CYAN}{filepath}{RESET}  (matches: {pat.pattern})"
                )
                found += 1
                break
    return found


def scan_content(files: list[str]) -> int:
    found = 0
    current_file = ""
    for filepath in files:
        if not os.path.isfile(filepath) or is_binary(filepath):
            continue
        try:
            with open(filepath, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError:
            continue

        for label, pat in _COMPILED_CONTENT:
            hits = 0
            for lineno, line in enumerate(lines, 1):
                for m in pat.finditer(line):
                    if hits >= 5:
                        break
                    if current_file != filepath:
                        print(f"\n  {CYAN}{filepath}{RESET}")
                        current_file = filepath
                    print(
                        f"    {RED}✗{RESET} L{lineno}: {YELLOW}[{label}]{RESET} {redact(m.group())}"
                    )
                    found += 1
                    hits += 1
                if hits >= 5:
                    break

    if found > 0:
        print(f"\n{BOLD}{RED}▸ {found} potential secret(s) in file content{RESET}")
    return found


def audit_gitignore() -> int:
    print(f"{BOLD}▸ .gitignore coverage audit{RESET}\n")
    missing = 0
    for pat in GITIGNORE_CHECK:
        rc, _ = git("check-ignore", "--no-index", "-q", pat)
        if rc == 0:
            print(f"  {GREEN}✓{RESET} {pat} — ignored")
        else:
            print(f"  {RED}✗{RESET} {pat} — {YELLOW}NOT in .gitignore{RESET}")
            missing += 1
    print()
    if missing == 0:
        print(f"{GREEN}All common sensitive patterns are covered by .gitignore{RESET}")
    else:
        print(f"{YELLOW}{missing} pattern(s) not covered by .gitignore{RESET}")
    return missing


# ── Main ─────────────────────────────────────────────────────────────


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "staged"
    target = sys.argv[2] if len(sys.argv) > 2 else ""

    if mode not in ("staged", "tracked", "path", "gitignore"):
        print(
            f"{RED}Usage: {sys.argv[0]} {{staged|tracked|path <dir>|gitignore}}{RESET}",
            file=sys.stderr,
        )
        return 2

    if mode == "gitignore":
        return 0 if audit_gitignore() == 0 else 1

    print(f"{BOLD}▸ Secret scan (mode: {mode}){RESET}")

    files = get_files(mode, target)
    if not files:
        print(f"{GREEN}No files to scan.{RESET}")
        return 0

    print(f"  Scanning {len(files)} file(s)...\n")

    total = scan_filenames(files)

    print(f"\n{BOLD}▸ Scanning file content for secret patterns...{RESET}")
    total += scan_content(files)

    print()
    if total == 0:
        print(f"{GREEN}{BOLD}✓ No secrets detected{RESET}")
        return 0
    else:
        print(f"{RED}{BOLD}⚠ {total} finding(s) — review before committing{RESET}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
