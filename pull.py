#!/usr/bin/env python3
"""
pull.py - Sync opencode configs from GitHub repo to user-level config.

Env:
  REPO_OWNER=ControlNet
  REPO_NAME=omo-dotfile
  REPO_REV=master
  CONFIG_DIR=<optional override>
  NO_BACKUP=1 (optional)
"""

import os
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
NO_BACKUP = os.environ.get("NO_BACKUP", "0") == "1"


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


def backup_and_install(src: Path, dst: Path, stamp: str) -> None:
    """Backup existing file if needed, then install new file."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not NO_BACKUP and dst.exists():
        backup_path = dst.with_suffix(f"{dst.suffix}.bak-{stamp}")
        shutil.copy2(dst, backup_path)
    shutil.copy2(src, dst)


def rename_json_if_exists(json_path: Path, stamp: str) -> None:
    """Rename .json to .json.bak if exists."""
    if json_path.exists():
        backup_path = json_path.with_suffix(f".json.bak-{stamp}")
        if backup_path.exists():
            backup_path = backup_path.with_suffix(f".bak-{stamp}-{os.getpid()}")
        json_path.rename(backup_path)


def copy_directory(src_dir: Path, dst_dir: Path) -> None:
    """Copy directory contents, preserving existing local files."""
    if not src_dir.exists():
        print(f"Warning: Source directory not found: {src_dir}", file=sys.stderr)
        return
    shutil.copytree(src_dir, dst_dir, dirs_exist_ok=True)


def main():
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    stamp = timestamp()

    repo_url = f"https://github.com/{REPO_OWNER}/{REPO_NAME}.git"

    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        repo_path = tmp_path / REPO_NAME

        # Step [1/4]: Clone repo (shallow)
        print(f"[1/4] Cloning repository (branch/tag: {REPO_REV})...")
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
            print(f"Error: Failed to clone repository", file=sys.stderr)
            print(result.stderr, file=sys.stderr)
            sys.exit(1)

        # Step [2/4]: Copy config files
        print(f"[2/4] Installing config files to: {config_dir}")
        config_files = [
            ("opencode.jsonc", "opencode.jsonc"),
            ("oh-my-opencode.jsonc", "oh-my-opencode.jsonc"),
            ("_AGENTS.md", "AGENTS.md"),
        ]
        for src_name, dst_name in config_files:
            src = repo_path / src_name
            dst = config_dir / dst_name
            if src.exists():
                print(f"      - {src_name}")
                backup_and_install(src, dst, stamp)

        # Step [3/4]: Copy plugins and skills directories
        print("[3/4] Installing plugins and skills...")
        for dir_name in ["plugins", "skills"]:
            src_dir = repo_path / dir_name
            dst_dir = config_dir / dir_name
            if src_dir.exists():
                print(f"      - {dir_name}/")
                copy_directory(src_dir, dst_dir)

        # Step [4/4]: Rename legacy .json files
        print("[4/4] Renaming legacy .json (if exists) so only .jsonc remains active")
        rename_json_if_exists(config_dir / "opencode.json", stamp)
        rename_json_if_exists(config_dir / "oh-my-opencode.json", stamp)

    print("Done.")
    print(f"Timestamp: {stamp}")
    if not NO_BACKUP:
        print(f"Backups: *.bak-{stamp}")


if __name__ == "__main__":
    main()
