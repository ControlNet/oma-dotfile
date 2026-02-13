#!/usr/bin/env python3
"""
pull.py - Sync opencode configs from GitHub repo to user-level config.

Env:
  REPO_OWNER=ControlNet
  REPO_NAME=omo-dotfile
  REPO_REV=master
  CONFIG_DIR=<optional override>
  CODEX_DIR=<optional override>
  CLAUDE_DIR=<optional override>
  CODEX_HOME=<optional override; used when CODEX_DIR is not set>
  NO_BACKUP=1 (optional)
  SETUP_NOTIFY_HOOKS=0 (optional; disable auto-configure Codex/Claude notify hooks)
  SETUP_NOTIFY_HOOKS_FORCE=1 (optional; replace existing Codex notify line; default off)
"""

import json
import os
import re
import sys
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
from tempfile import TemporaryDirectory

# Config from environment
REPO_OWNER = os.environ.get("REPO_OWNER", "ControlNet")
REPO_NAME = os.environ.get("REPO_NAME", "omo-dotfile")
REPO_REV = os.environ.get("REPO_REV", "master")
CONFIG_DIR_ENV = os.environ.get("CONFIG_DIR", "")
CODEX_DIR_ENV = os.environ.get("CODEX_DIR", "")
CLAUDE_DIR_ENV = os.environ.get("CLAUDE_DIR", "")
NO_BACKUP = os.environ.get("NO_BACKUP", "0") == "1"
SETUP_NOTIFY_HOOKS = os.environ.get("SETUP_NOTIFY_HOOKS", "1") == "1"
SETUP_NOTIFY_HOOKS_FORCE = os.environ.get("SETUP_NOTIFY_HOOKS_FORCE", "0") == "1"

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
{MAGENTA}{BOLD}                         ██████╗ ███╗   ███╗ ██████╗ 
                        ██╔═══██╗████╗ ████║██╔═══██╗
                        ██║   ██║██╔████╔██║██║   ██║
                        ██║   ██║██║╚██╔╝██║██║   ██║
                        ╚██████╔╝██║ ╚═╝ ██║╚██████╔╝
                         ╚═════╝ ╚═╝     ╚═╝ ╚═════╝ 
{RESET}
{CYAN}  ══════════════════════════════════════════════════════════════════════════════
{YELLOW}                    Oh-My-OpenCode Configuration Installer
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


def get_claude_dir() -> Path:
    """Determine Claude Code home directory."""
    if CLAUDE_DIR_ENV:
        return Path(CLAUDE_DIR_ENV)
    return Path.home() / ".claude"


MAX_BACKUPS = 5


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
        shutil.copy2(dst, backup_path)
        cleanup_old_backups(dst)
    shutil.copy2(src, dst)


def rename_json_if_exists(json_path: Path, stamp: str) -> None:
    """Rename .json to .json.bak if exists."""
    if json_path.exists():
        backup_path = json_path.with_suffix(f".json.bak-{stamp}")
        if backup_path.exists():
            backup_path = backup_path.with_suffix(f".bak-{stamp}-{os.getpid()}")
        json_path.rename(backup_path)


def copy_directory(src_dir: Path, dst_dir: Path) -> None:
    if not src_dir.exists():
        warn(f"Source directory not found: {src_dir}")
        return
    if dst_dir.exists():
        shutil.rmtree(dst_dir)
    shutil.copytree(src_dir, dst_dir)


def copy_directory_merge(src_dir: Path, dst_dir: Path) -> None:
    """Merge-copy directory contents while preserving unrelated existing files."""
    if not src_dir.exists():
        warn(f"Source directory not found: {src_dir}")
        return
    dst_dir.mkdir(parents=True, exist_ok=True)
    for entry in src_dir.iterdir():
        target = dst_dir / entry.name
        if entry.is_dir():
            shutil.copytree(entry, target, dirs_exist_ok=True)
        else:
            shutil.copy2(entry, target)


def backup_file_if_exists(path: Path, stamp: str) -> None:
    if NO_BACKUP or not path.exists():
        return
    backup_path = path.with_suffix(f"{path.suffix}.bak-{stamp}")
    shutil.copy2(path, backup_path)
    cleanup_old_backups(path)


def ensure_codex_notify_config(codex_dir: Path, stamp: str) -> None:
    config_path = codex_dir / "config.toml"
    python_bin = sys.executable or "python3"
    script_path = codex_dir / "codex-gotify-notify.py"
    desired_line = f'notify = ["{python_bin}", "{script_path}"]'

    if not config_path.exists():
        config_path.write_text(desired_line + "\n", encoding="utf-8")
        success(f"Created Codex notify config: {config_path}")
        return

    try:
        content = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        warn(f"Failed to read {config_path}: {exc}")
        return

    if "codex-gotify-notify.py" in content:
        # Might still be in a non-top-level section from old installer logic.
        # Continue and normalize location instead of early return.
        pass

    lines = content.splitlines()
    first_section_idx = None
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            first_section_idx = idx
            break

    top_notify_idx = None
    any_notify_idx = []
    notify_with_codex_idx = []
    for idx, line in enumerate(lines):
        if re.match(r"^\s*notify\s*=", line):
            any_notify_idx.append(idx)
            if "codex-gotify-notify.py" in line:
                notify_with_codex_idx.append(idx)
            if first_section_idx is None or idx < first_section_idx:
                top_notify_idx = idx

    if top_notify_idx is not None:
        top_line = lines[top_notify_idx].strip()
        if top_line == desired_line:
            info("Codex notify hook already configured; skip")
            return
        if not SETUP_NOTIFY_HOOKS_FORCE:
            warn(
                "Codex config already has top-level notify=. "
                "Set SETUP_NOTIFY_HOOKS_FORCE=1 to replace automatically."
            )
            return
        lines[top_notify_idx] = desired_line
        backup_file_if_exists(config_path, stamp)
        config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        success("Replaced existing top-level Codex notify configuration")
        return

    # Remove misplaced codex notify entries (e.g. inserted inside a table).
    if notify_with_codex_idx:
        for idx in reversed(notify_with_codex_idx):
            lines.pop(idx)

    # If user has notify entries elsewhere and they're not our codex line, be conservative.
    has_foreign_notify = len(any_notify_idx) > len(notify_with_codex_idx)
    if has_foreign_notify and not SETUP_NOTIFY_HOOKS_FORCE:
        warn(
            "Codex config has existing notify entries in non-top-level context. "
            "Set SETUP_NOTIFY_HOOKS_FORCE=1 to insert top-level notify automatically."
        )
        return

    insert_idx = first_section_idx if first_section_idx is not None else len(lines)
    lines.insert(insert_idx, desired_line)
    backup_file_if_exists(config_path, stamp)
    config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    success("Inserted top-level Codex notify configuration")


def ensure_claude_notify_config(claude_dir: Path, stamp: str) -> None:
    settings_path = claude_dir / "settings.json"
    python_bin = sys.executable or "python3"
    script_path = claude_dir / "claude-gotify-notify.py"
    command = f'"{python_bin}" "{script_path}"'

    desired_hooks = {
        "Notification": [
            {
                "matcher": "permission_prompt|idle_prompt|elicitation_dialog",
                "hooks": [{"type": "command", "command": command}],
            }
        ],
        "Stop": [{"hooks": [{"type": "command", "command": command}]}],
        "SubagentStop": [{"hooks": [{"type": "command", "command": command}]}],
        "PermissionRequest": [{"hooks": [{"type": "command", "command": command}]}],
        "PostToolUseFailure": [{"hooks": [{"type": "command", "command": command}]}],
    }

    data: dict[str, object]
    if settings_path.exists():
        try:
            raw = settings_path.read_text(encoding="utf-8")
            parsed = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            warn(f"Failed to parse {settings_path}: {exc}")
            warn("Skip auto-setup for Claude hooks; please merge manually.")
            return
        if not isinstance(parsed, dict):
            warn(f"Unexpected JSON root in {settings_path}; skip auto-setup.")
            return
        data = parsed
    else:
        data = {}

    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
        data["hooks"] = hooks

    changed = False
    for event_name, desired_groups in desired_hooks.items():
        existing_groups = hooks.get(event_name)
        if not isinstance(existing_groups, list):
            hooks[event_name] = desired_groups
            changed = True
            continue

        for desired_group in desired_groups:
            desired_matcher = desired_group.get("matcher")
            match_idx = None
            for idx, group in enumerate(existing_groups):
                if not isinstance(group, dict):
                    continue
                if group.get("matcher") == desired_matcher:
                    match_idx = idx
                    break

            if match_idx is None:
                existing_groups.append(desired_group)
                changed = True
                continue

            group_obj = existing_groups[match_idx]
            group_hooks = group_obj.get("hooks")
            if not isinstance(group_hooks, list):
                group_obj["hooks"] = desired_group["hooks"]
                changed = True
                continue

            already_has = False
            for hook in group_hooks:
                if not isinstance(hook, dict):
                    continue
                if hook.get("type") == "command" and hook.get("command") == command:
                    already_has = True
                    break
            if not already_has:
                group_hooks.append({"type": "command", "command": command})
                changed = True

    if not changed:
        info("Claude notify hooks already configured; skip")
        return

    backup_file_if_exists(settings_path, stamp)
    settings_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    success(f"Updated Claude hooks config: {settings_path}")


def main():
    print(BANNER)

    config_dir = get_config_dir()
    codex_dir = get_codex_dir()
    claude_dir = get_claude_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    codex_dir.mkdir(parents=True, exist_ok=True)
    claude_dir.mkdir(parents=True, exist_ok=True)
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
        config_files = [
            ("opencode.jsonc", "opencode.jsonc"),
            ("oh-my-opencode.jsonc", "oh-my-opencode.jsonc"),
            ("_AGENTS.md", "AGENTS.md"),
        ]
        for src_name, dst_name in config_files:
            src = repo_path / src_name
            dst = config_dir / dst_name
            if src.exists():
                print(f"         - {src_name}")
                backup_and_install(src, dst, stamp)

        info("[3/7] Installing OpenCode plugins and skills...")
        for dir_name in ["plugins", "skills"]:
            src_dir = repo_path / dir_name
            dst_dir = config_dir / dir_name
            if src_dir.exists():
                print(f"         - {dir_name}/")
                copy_directory(src_dir, dst_dir)

        info(f"[4/7] Installing shared Codex assets to: {codex_dir}")
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

        info(f"[5/7] Installing shared Claude Code assets to: {claude_dir}")
        claude_files = [
            ("_AGENTS.md", "CLAUDE.md"),
            ("claude-gotify-notify.py", "claude-gotify-notify.py"),
        ]
        for src_name, dst_name in claude_files:
            src = repo_path / src_name
            dst = claude_dir / dst_name
            if src.exists():
                print(f"         - {src_name} -> {dst_name}")
                backup_and_install(src, dst, stamp)

        claude_skills_src = repo_path / "skills"
        claude_skills_dst = claude_dir / "skills"
        if claude_skills_src.exists():
            print("         - skills/ (merge)")
            copy_directory_merge(claude_skills_src, claude_skills_dst)

        info("[6/7] Renaming legacy .json (if exists) so only .jsonc remains active")
        rename_json_if_exists(config_dir / "opencode.json", stamp)
        rename_json_if_exists(config_dir / "oh-my-opencode.json", stamp)

        info("[7/7] Optionally configuring Codex/Claude notify hooks")
        if SETUP_NOTIFY_HOOKS:
            ensure_codex_notify_config(codex_dir, stamp)
            ensure_claude_notify_config(claude_dir, stamp)
        else:
            info("SETUP_NOTIFY_HOOKS=0; skip hook auto-setup")

    print()
    success("Installation complete!")
    info(f"Timestamp: {stamp}")
    if not NO_BACKUP:
        info(f"Backups: *.bak-{stamp}")


if __name__ == "__main__":
    main()
