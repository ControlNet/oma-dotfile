#!/usr/bin/env python3
"""
pull.py - Sync opencode configs from GitHub repo to user-level config.

Env:
  REPO_OWNER=ControlNet
  REPO_NAME=oma-dotfile
  REPO_REV=master
  CONFIG_DIR=<optional override>
  CODEX_DIR=<optional override>
  CODEX_HOME=<optional override; used when CODEX_DIR is not set>
  OMP_AGENT_DIR=<optional override for ~/.omp/agent>
  PI_CODING_AGENT_DIR=<oh-my-pi native override; used when OMP_AGENT_DIR is not set>
  NO_BACKUP=1 (optional)
"""

import os
import json
import re
import sys
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
from tempfile import TemporaryDirectory

# Config from environment
REPO_OWNER = os.environ.get("REPO_OWNER", "ControlNet")
REPO_NAME = os.environ.get("REPO_NAME", "oma-dotfile")
REPO_REV = os.environ.get("REPO_REV", "master")
CONFIG_DIR_ENV = os.environ.get("CONFIG_DIR", "")
CODEX_DIR_ENV = os.environ.get("CODEX_DIR", "")
OMP_AGENT_DIR_ENV = os.environ.get("OMP_AGENT_DIR", "").strip()
NO_BACKUP = os.environ.get("NO_BACKUP", "0") == "1"
REQUIRED_ENV_VARS = [
    "CODEX_BASE_URL",
    "CODEX_API_KEY",
    "GITHUB_PERSONAL_ACCESS_TOKEN",
]

# ─────────────────────────────────────────────────────────────────────────────
# COLORS & STYLES (ANSI escape codes)
# ─────────────────────────────────────────────────────────────────────────────
RESET = "\033[0m"
BOLD = "\033[1m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
MAGENTA = "\033[35m"

BANNER = f"""{CYAN}{BOLD}
 ██████╗ ██████╗ ███╗   ██╗████████╗██████╗  ██████╗ ██╗     ███╗   ██╗███████╗████████╗
██╔════╝██╔═══██╗████╗  ██║╚══██╔══╝██╔══██╗██╔═══██╗██║     ████╗  ██║██╔════╝╚══██╔══╝
██║     ██║   ██║██╔██╗ ██║   ██║   ██████╔╝██║   ██║██║     ██╔██╗ ██║█████╗     ██║   
██║     ██║   ██║██║╚██╗██║   ██║   ██╔══██╗██║   ██║██║     ██║╚██╗██║██╔══╝     ██║   
╚██████╗╚██████╔╝██║ ╚████║   ██║   ██║  ██║╚██████╔╝███████╗██║ ╚████║███████╗   ██║   
 ╚═════╝ ╚═════╝ ╚═╝  ╚═══╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝╚══════╝   ╚═╝   
{RESET}
{MAGENTA}{BOLD}                         ██████╗ ███╗   ███╗ █████╗ 
                        ██╔═══██╗████╗ ████║██╔══██╗
                        ██║   ██║██╔████╔██║███████║
                        ██║   ██║██║╚██╔╝██║██╔══██║
                        ╚██████╔╝██║ ╚═╝ ██║██║  ██║
                        ╚═════╝ ╚═╝     ╚═╝╚═╝  ╚═╝
{RESET}
{CYAN}  ══════════════════════════════════════════════════════════════════════════════
{YELLOW}                ControlNet Oh-My-Agents Configuration Installer
{CYAN}  ══════════════════════════════════════════════════════════════════════════════{RESET}
"""


def info(msg: str) -> None:
    """Print info message with cyan color."""
    print(f"{CYAN}{BOLD}[INFO]{RESET}    {msg}")


def success(msg: str) -> None:
    """Print success message with green color."""
    print(f"{GREEN}{BOLD}[SUCCESS]{RESET} {msg}")


def warn(msg: str) -> None:
    """Print warning message with yellow color."""
    print(f"{YELLOW}{BOLD}[WARN]{RESET}    {msg}", file=sys.stderr)


def error(msg: str) -> None:
    """Print error message with red color and exit."""
    print(f"{RED}{BOLD}[ERROR]{RESET}   {msg}", file=sys.stderr)


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def warn_missing_required_env_vars() -> None:
    missing = [
        name for name in REQUIRED_ENV_VARS if not os.environ.get(name, "").strip()
    ]
    if not missing:
        info("All required environment variables are present")
        return

    info("Missing required environment variables from README:")
    for name in missing:
        info(f"  - {name}")
    info("Script will continue, but related features may not work as expected.")


def get_config_dir() -> Path:
    """Determine user-level config directory."""
    if CONFIG_DIR_ENV:
        return Path(CONFIG_DIR_ENV)
    if sys.platform == "win32":
        return Path.home() / ".config" / "opencode"
    xdg_config = os.environ.get("XDG_CONFIG_HOME", "")
    if xdg_config:
        return Path(xdg_config) / "opencode"
    return Path.home() / ".config" / "opencode"


def get_codex_dir() -> Path:
    """Determine Codex home directory."""
    if CODEX_DIR_ENV:
        return Path(CODEX_DIR_ENV)
    codex_home = os.environ.get("CODEX_HOME", "").strip()
    if codex_home:
        return Path(codex_home)
    return Path.home() / ".codex"


def get_omp_agent_dir() -> Path:
    """Determine oh-my-pi agent config directory."""
    if OMP_AGENT_DIR_ENV:
        return Path(OMP_AGENT_DIR_ENV)
    pi_agent_dir = os.environ.get("PI_CODING_AGENT_DIR", "").strip()
    if pi_agent_dir:
        return Path(pi_agent_dir)
    return Path.home() / ".omp" / "agent"


MAX_BACKUPS = max(1, int(os.environ.get("MAX_BACKUPS", "1")))

OPENCODE_CONFIG_FILES = [
    ("opencode.jsonc", "opencode.jsonc"),
    ("oh-my-openagent.jsonc", "oh-my-openagent.jsonc"),
    ("tui.json", "tui.json"),
    ("_AGENTS.md", "AGENTS.md"),
]

LEGACY_OPENAGENT_CONFIG_NAMES = [
    "oh-my-opencode.json",
    "oh-my-opencode.jsonc",
    "oh-my-openagent.json",
]


def cleanup_old_backups(file_path: Path) -> None:
    pattern = f"{file_path.name}.bak-*"
    backups = sorted(file_path.parent.glob(pattern), key=lambda p: p.stat().st_mtime)
    while len(backups) > MAX_BACKUPS:
        oldest = backups.pop(0)
        oldest.unlink()
        info(f"Removed old backup: {oldest.name}")


def backup_and_install(src: Path, dst: Path, stamp: str) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not NO_BACKUP and dst.exists():
        backup_path = dst.with_suffix(f"{dst.suffix}.bak-{stamp}")
        _ = shutil.copy2(dst, backup_path)
        cleanup_old_backups(dst)
    _ = shutil.copy2(src, dst)


def rename_path_if_exists(path: Path, stamp: str) -> None:
    """Rename an existing file to a timestamped backup."""
    if path.exists():
        if path.suffix:
            backup_path = path.with_suffix(f"{path.suffix}.bak-{stamp}")
        else:
            backup_path = path.with_name(f"{path.name}.bak-{stamp}")
        if backup_path.exists():
            backup_path = backup_path.with_suffix(f".bak-{stamp}-{os.getpid()}")
        _ = path.rename(backup_path)
        cleanup_old_backups(path)


def install_opencode_config_files(repo_path: Path, config_dir: Path, stamp: str) -> None:
    for src_name, dst_name in OPENCODE_CONFIG_FILES:
        src = repo_path / src_name
        dst = config_dir / dst_name
        if src.exists():
            print(f"         - {src_name}")
            backup_and_install(src, dst, stamp)


def retire_legacy_openagent_files(config_dir: Path, stamp: str) -> None:
    for name in LEGACY_OPENAGENT_CONFIG_NAMES:
        rename_path_if_exists(config_dir / name, stamp)


def copy_directory(src_dir: Path, dst_dir: Path) -> None:
    if not src_dir.exists():
        warn(f"Source directory not found: {src_dir}")
        return
    if dst_dir.exists():
        shutil.rmtree(dst_dir)
    _ = shutil.copytree(src_dir, dst_dir)


def copy_directory_merge(src_dir: Path, dst_dir: Path) -> None:
    """Merge-copy directory contents while preserving unrelated existing files."""
    if not src_dir.exists():
        warn(f"Source directory not found: {src_dir}")
        return
    dst_dir.mkdir(parents=True, exist_ok=True)
    for entry in src_dir.iterdir():
        target = dst_dir / entry.name
        if entry.is_dir():
            _ = shutil.copytree(entry, target, dirs_exist_ok=True)
        else:
            _ = shutil.copy2(entry, target)


def backup_file_if_exists(path: Path, stamp: str) -> None:
    if NO_BACKUP or not path.exists():
        return
    backup_path = path.with_suffix(f"{path.suffix}.bak-{stamp}")
    _ = shutil.copy2(path, backup_path)
    cleanup_old_backups(path)


def render_omp_models(content: str, codex_base_url: str) -> tuple[str, bool]:
    """Render omp_models.yaml by inlining CODEX_BASE_URL placeholder."""
    pattern = re.compile(
        r'^(\s*baseUrl:\s*)(["\']?)CODEX_BASE_URL\2(\s*(?:#.*)?)$', re.MULTILINE
    )
    quoted_url = json.dumps(codex_base_url)
    rendered, count = pattern.subn(
        lambda m: f"{m.group(1)}{quoted_url}{m.group(3)}", content
    )
    return rendered, count > 0


def backup_and_install_omp_models(src: Path, dst: Path, stamp: str) -> None:
    """Install models.yml for oh-my-pi and inline CODEX_BASE_URL."""
    try:
        content = src.read_text(encoding="utf-8")
    except OSError as exc:
        warn(f"Failed to read {src}: {exc}")
        return

    codex_base_url = os.environ.get("CODEX_BASE_URL", "").strip()
    if codex_base_url:
        content, replaced = render_omp_models(content, codex_base_url)
        if replaced:
            info("Injected CODEX_BASE_URL into omp models.yml")
        else:
            warn("No `baseUrl: CODEX_BASE_URL` placeholder found in omp_models.yaml")
    else:
        warn("CODEX_BASE_URL is not set; leaving `baseUrl: CODEX_BASE_URL` in omp models.yml. oh-my-pi will not auto-expand it.")

    dst.parent.mkdir(parents=True, exist_ok=True)
    if not NO_BACKUP and dst.exists():
        backup_path = dst.with_suffix(f"{dst.suffix}.bak-{stamp}")
        _ = shutil.copy2(dst, backup_path)
        cleanup_old_backups(dst)
    try:
        _ = dst.write_text(content, encoding="utf-8")
    except OSError as exc:
        warn(f"Failed to write {dst}: {exc}")


def find_first_toml_section_idx(lines: list[str]) -> int | None:
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            return idx
    return None


def ensure_top_level_config_line(lines: list[str], desired_line: str, key: str) -> list[str]:
    first_section_idx = find_first_toml_section_idx(lines)
    key_pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    matching_indexes = [
        idx
        for idx, line in enumerate(lines)
        if key_pattern.match(line) and (first_section_idx is None or idx < first_section_idx)
    ]

    if matching_indexes:
        matching_set = set(matching_indexes)
        new_lines: list[str] = []
        wrote_line = False
        for idx, line in enumerate(lines):
            if idx in matching_set:
                if not wrote_line:
                    new_lines.append(desired_line)
                    wrote_line = True
                continue
            new_lines.append(line)
        return new_lines

    insert_idx = first_section_idx if first_section_idx is not None else len(lines)
    return [*lines[:insert_idx], desired_line, *lines[insert_idx:]]


def replace_toml_section(lines: list[str], section_name: str, section_lines: list[str]) -> list[str]:
    section_header = f"[{section_name}]"
    section_start = None
    for idx, line in enumerate(lines):
        if line.strip() == section_header:
            section_start = idx
            break

    if section_start is None:
        if lines and lines[-1].strip():
            return [*lines, "", *section_lines]
        return [*lines, *section_lines]

    section_end = len(lines)
    for idx in range(section_start + 1, len(lines)):
        stripped = lines[idx].strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section_end = idx
            break

    return [*lines[:section_start], *section_lines, *lines[section_end:]]


def ensure_codex_api_provider_config(lines: list[str]) -> list[str]:
    codex_base_url = os.environ.get("CODEX_BASE_URL", "").strip()
    if not codex_base_url:
        warn("CODEX_BASE_URL is not set; skip Codex model provider config in config.toml.")
        return lines

    lines = ensure_top_level_config_line(
        lines,
        'model_provider = "codex_api"',
        "model_provider",
    )
    return replace_toml_section(
        lines,
        "model_providers.codex_api",
        [
            "[model_providers.codex_api]",
            'name = "codex_api"',
            f"base_url = {json.dumps(codex_base_url)}",
            'env_key = "CODEX_API_KEY"',
            'wire_api = "responses"',
        ],
    )


def ensure_codex_notify_config_lines(lines: list[str], codex_dir: Path) -> list[str]:
    python_bin = sys.executable or "python3"
    script_path = codex_dir / "codex-gotify-notify.py"
    desired_line = f'notify = ["{python_bin}", "{script_path}"]'
    first_section_idx = find_first_toml_section_idx(lines)
    any_notify_idx: list[int] = []
    for idx, line in enumerate(lines):
        if re.match(r"^\s*notify\s*=", line):
            any_notify_idx.append(idx)

    if any_notify_idx:
        notify_idx_set = set(any_notify_idx)
        new_lines: list[str] = []
        wrote_top_notify = False
        for idx, line in enumerate(lines):
            if idx in notify_idx_set:
                is_top_level = first_section_idx is None or idx < first_section_idx
                if is_top_level and not wrote_top_notify:
                    new_lines.append(desired_line)
                    wrote_top_notify = True
                continue
            new_lines.append(line)

        if not wrote_top_notify:
            insert_idx = find_first_toml_section_idx(new_lines)
            if insert_idx is None:
                insert_idx = len(new_lines)
            new_lines.insert(insert_idx, desired_line)
        return new_lines

    insert_idx = first_section_idx if first_section_idx is not None else len(lines)
    return [*lines[:insert_idx], desired_line, *lines[insert_idx:]]


def ensure_codex_config(codex_dir: Path, stamp: str) -> None:
    config_path = codex_dir / "config.toml"
    if config_path.exists():
        try:
            content = config_path.read_text(encoding="utf-8")
        except OSError as exc:
            warn(f"Failed to read {config_path}: {exc}")
            return
        lines = content.splitlines()
    else:
        lines = []

    new_lines = ensure_codex_notify_config_lines(lines, codex_dir)
    new_lines = ensure_codex_api_provider_config(new_lines)

    if new_lines == lines:
        info("Codex config already configured; skip")
        return

    backup_file_if_exists(config_path, stamp)
    _ = config_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    success(f"Configured Codex config: {config_path}")


def main():
    print(BANNER)
    warn_missing_required_env_vars()

    config_dir = get_config_dir()
    codex_dir = get_codex_dir()
    omp_agent_dir = get_omp_agent_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    codex_dir.mkdir(parents=True, exist_ok=True)
    omp_agent_dir.mkdir(parents=True, exist_ok=True)
    stamp = timestamp()

    repo_url = f"https://github.com/{REPO_OWNER}/{REPO_NAME}.git"

    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        repo_path = tmp_path / REPO_NAME

        info(f"[1/7] Cloning repository (branch/tag: {REPO_REV})...")
        result = subprocess.run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--branch",
                REPO_REV,
                repo_url,
                str(repo_path),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            error(f"Failed to clone repository")
            print(result.stderr, file=sys.stderr)
            sys.exit(1)

        info(f"[2/7] Installing OpenCode config files to: {config_dir}")
        install_opencode_config_files(repo_path, config_dir, stamp)

        info("[3/7] Installing OpenCode plugins and skills...")
        for dir_name in ["plugins", "skills"]:
            src_dir = repo_path / dir_name
            dst_dir = config_dir / dir_name
            if src_dir.exists():
                print(f"         - {dir_name}/")
                copy_directory(src_dir, dst_dir)

        info(f"[4/7] Installing oh-my-pi config files to: {omp_agent_dir}")
        omp_config_files = [
            ("omp_config.yml", "config.yml"),
        ]
        for src_name, dst_name in omp_config_files:
            src = repo_path / src_name
            dst = omp_agent_dir / dst_name
            if src.exists():
                print(f"         - {src_name}")
                backup_and_install(src, dst, stamp)

        omp_extension_files = [
            ("omp-gotify-notify.js", "extensions/omp-gotify-notify.js"),
        ]
        for src_name, dst_name in omp_extension_files:
            src = repo_path / src_name
            dst = omp_agent_dir / dst_name
            if src.exists():
                print(f"         - {src_name}")
                backup_and_install(src, dst, stamp)

        omp_models_src = repo_path / "omp_models.yaml"
        omp_models_dst = omp_agent_dir / "models.yml"
        if omp_models_src.exists():
            print("         - omp_models.yaml (render CODEX_BASE_URL)")
            backup_and_install_omp_models(omp_models_src, omp_models_dst, stamp)

        info(f"[5/7] Installing shared Codex assets to: {codex_dir}")
        codex_files = [
            ("_AGENTS.md", "AGENTS.md"),
            ("codex-gotify-notify.py", "codex-gotify-notify.py"),
        ]
        for src_name, dst_name in codex_files:
            src = repo_path / src_name
            dst = codex_dir / dst_name
            if src.exists():
                print(f"         - {src_name}")
                backup_and_install(src, dst, stamp)

        codex_skills_src = repo_path / "skills"
        codex_skills_dst = codex_dir / "skills"
        if codex_skills_src.exists():
            print("         - skills/ (merge)")
            copy_directory_merge(codex_skills_src, codex_skills_dst)

        info("[6/7] Retiring legacy OpenAgent config names so only current .jsonc remains active")
        rename_path_if_exists(config_dir / "opencode.json", stamp)
        retire_legacy_openagent_files(config_dir, stamp)

        info("[7/7] Configuring Codex config")
        ensure_codex_config(codex_dir, stamp)

    print()
    success("Installation complete!")
    info(f"Timestamp: {stamp}")
    if not NO_BACKUP:
        info(f"Backups: *.bak-{stamp} (keep last {MAX_BACKUPS} per file)")


if __name__ == "__main__":
    main()
