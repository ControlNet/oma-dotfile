#!/usr/bin/env python3
"""
pull.py - Sync agent configs from GitHub repo to user-level locations.

Env:
  REPO_OWNER=ControlNet
  REPO_NAME=oma-dotfile
  REPO_REV=master
  CONFIG_DIR=<optional override>
  CODEX_DIR=<optional override>
  CODEX_HOME=<optional override; used when CODEX_DIR is not set>
  CLAUDE_CONFIG_DIR=<optional override for ~/.claude>
  OMP_AGENT_DIR=<optional override for ~/.omp/agent>
  PI_CODING_AGENT_DIR=<oh-my-pi native override; used when OMP_AGENT_DIR is not set>
  TOKSCALE_CONFIG_DIR=<optional override for tokscale settings directory>
  WAKATIME_HOME=<optional override for the .wakatime.cfg location>
  NO_BACKUP=1 (optional)
"""

import argparse
import json
import os
import re
import shutil
import sys
import tomllib
import subprocess
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

# Config from environment
REPO_OWNER = os.environ.get("REPO_OWNER", "ControlNet")
REPO_NAME = os.environ.get("REPO_NAME", "oma-dotfile")
REPO_REV = os.environ.get("REPO_REV", "master")
CONFIG_DIR_ENV = os.environ.get("CONFIG_DIR", "")
CODEX_DIR_ENV = os.environ.get("CODEX_DIR", "")
CLAUDE_CONFIG_DIR_ENV = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
OMP_AGENT_DIR_ENV = os.environ.get("OMP_AGENT_DIR", "").strip()
NO_BACKUP = os.environ.get("NO_BACKUP", "0") == "1"
REQUIRED_ENV_VARS = [
    "CODEX_BASE_URL",
    "CODEX_API_TOKEN",
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


def warn_missing_required_env_vars(oauth: bool = False) -> None:
    missing = [
        name for name in REQUIRED_ENV_VARS
        if not (oauth and name in {"CODEX_BASE_URL", "CODEX_API_TOKEN"})
        and not os.environ.get(name, "").strip()
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


def get_claude_config_dir() -> Path:
    """Determine Claude Code's user-level configuration directory."""
    if CLAUDE_CONFIG_DIR_ENV:
        return Path(CLAUDE_CONFIG_DIR_ENV).expanduser()
    return Path.home() / ".claude"


def get_omp_agent_dir() -> Path:
    """Determine oh-my-pi agent config directory."""
    if OMP_AGENT_DIR_ENV:
        return Path(OMP_AGENT_DIR_ENV)
    pi_agent_dir = os.environ.get("PI_CODING_AGENT_DIR", "").strip()
    if pi_agent_dir:
        return Path(pi_agent_dir)
    return Path.home() / ".omp" / "agent"


def get_tokscale_config_dir() -> Path:
    """Follow Tokscale's platform defaults and native directory override."""
    override = os.environ.get("TOKSCALE_CONFIG_DIR", "")
    if override:
        return Path(override)
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "tokscale"
    if sys.platform != "darwin" and os.environ.get("XDG_CONFIG_HOME"):
        return Path(os.environ["XDG_CONFIG_HOME"]) / "tokscale"
    return Path.home() / ".config" / "tokscale"


MAX_BACKUPS = max(1, int(os.environ.get("MAX_BACKUPS", "1")))

OPENCODE_CONFIG_FILES = [
    ("opencode.jsonc", "opencode.jsonc"),
    ("tui.json", "tui.json"),
    ("_AGENTS.md", "AGENTS.md"),
]

LEGACY_OPENAGENT_CONFIG_NAMES = [
    "oh-my-opencode.json",
    "oh-my-opencode.jsonc",
    "oh-my-openagent.json",
    "oh-my-openagent.jsonc",
]

LEGACY_OMO_CONFIG_NAMES = [
    "config.json",
    "config.jsonc",
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


# Keep JSON strings intact while accepting JSONC comments and trailing commas.
JSONC_TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/', re.DOTALL)


def read_jsonc_object(path: Path) -> dict:
    content = JSONC_TOKEN.sub(
        lambda match: match.group() if match.group().startswith('"') else " ",
        path.read_text(encoding="utf-8"),
    )
    content = re.sub(
        r'"(?:\\.|[^"\\])*"|,\s*(?=[}\]])',
        lambda match: match.group() if match.group().startswith('"') else "",
        content,
    )
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def install_rendered_text(content: str, dst: Path, stamp: str) -> None:
    """Back up and install rendered configuration without rewriting identical files."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and dst.read_text(encoding="utf-8") == content:
        return
    backup_file_if_exists(dst, stamp)
    dst.write_text(content, encoding="utf-8")


def install_opencode_config_files(
    repo_path: Path, config_dir: Path, stamp: str, oauth: bool = False
) -> None:
    for src_name, dst_name in OPENCODE_CONFIG_FILES:
        src = repo_path / src_name
        dst = config_dir / dst_name
        if src.exists():
            print(f"         - {src_name}")
            if oauth and src_name == "opencode.jsonc":
                document = read_jsonc_object(src)
                providers = document.setdefault("provider", {})
                providers.pop("codex", None)
                # OpenCode loads JSON before JSONC; JSONC wins on conflicts.
                existing_codex = {}
                has_codex = False
                for existing_path in (config_dir / "opencode.json", dst):
                    if existing_path.exists():
                        existing = read_jsonc_object(existing_path).get("provider", {})
                        if not isinstance(existing, dict):
                            raise ValueError(f"Expected provider object in {existing_path}")
                        if "codex" in existing:
                            if not isinstance(existing["codex"], dict):
                                raise ValueError(f"Expected codex provider object in {existing_path}")
                            existing_codex = merge_config_objects(existing_codex, existing["codex"])
                            has_codex = True
                if has_codex:
                    providers["codex"] = existing_codex
                install_rendered_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", dst, stamp)
            else:
                backup_and_install(src, dst, stamp)


def merge_config_objects(base: dict, override: dict) -> dict:
    """Merge legacy JSON and JSONC provider objects in load order."""
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_config_objects(result[key], value)
        else:
            result[key] = value
    return result


def install_omo_config(
    repo_path: Path, omo_dir: Path, stamp: str, oauth: bool = False
) -> None:
    src = repo_path / "omo.jsonc"
    print("         - omo.jsonc")
    if oauth:
        content = JSONC_TOKEN.sub(
            lambda match: match.group().replace('"codex/', '"openai/', 1)
            if match.group().startswith('"codex/') else match.group(),
            src.read_text(encoding="utf-8"),
        )
        install_rendered_text(content, omo_dir / "omo.jsonc", stamp)
    else:
        backup_and_install(src, omo_dir / "omo.jsonc", stamp)


def install_omp_config(src: Path, dst: Path, stamp: str, oauth: bool = False) -> None:
    if oauth:
        content = src.read_text(encoding="utf-8").replace("codex_api/", "openai-codex/")
        install_rendered_text(content, dst, stamp)
    else:
        backup_and_install(src, dst, stamp)


def retire_legacy_openagent_files(config_dir: Path, stamp: str) -> None:
    for name in LEGACY_OPENAGENT_CONFIG_NAMES:
        rename_path_if_exists(config_dir / name, stamp)


def retire_legacy_omo_files(omo_dir: Path, stamp: str) -> None:
    for name in LEGACY_OMO_CONFIG_NAMES:
        rename_path_if_exists(omo_dir / name, stamp)


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


def copy_directory_items_replace(src_dir: Path, dst_dir: Path) -> None:
    if not src_dir.exists():
        warn(f"Source directory not found: {src_dir}")
        return
    dst_dir.mkdir(parents=True, exist_ok=True)
    for entry in src_dir.iterdir():
        target = dst_dir / entry.name
        if target.exists() or target.is_symlink():
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            else:
                target.unlink()
        if entry.is_dir():
            _ = shutil.copytree(entry, target)
        else:
            _ = shutil.copy2(entry, target)


def install_claude_plugin(
    repo_path: Path, claude_config_dir: Path, _stamp: str
) -> None:
    """Install the managed Claude Code plugin without touching other skills."""
    src_dir = repo_path / "claude-plugins" / "gotify-notify"
    dst_dir = claude_config_dir / "skills" / "gotify-notify"
    if not src_dir.is_dir():
        warn(f"Source directory not found: {src_dir}")
        return

    copy_directory(src_dir, dst_dir)

    hooks_path = dst_dir / "hooks" / "hooks.json"
    try:
        hooks_document = json.loads(hooks_path.read_text(encoding="utf-8"))
        for event_entries in hooks_document["hooks"].values():
            for event_entry in event_entries:
                for hook in event_entry["hooks"]:
                    if hook.get("type") == "command":
                        hook["command"] = sys.executable or "python3"
        _ = hooks_path.write_text(
            json.dumps(hooks_document, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        warn(f"Failed to render Claude Code hooks: {exc}")
        return

    success(f"Installed Claude Code plugin: {dst_dir}")


def backup_file_if_exists(path: Path, stamp: str) -> None:
    if NO_BACKUP or not path.exists():
        return
    backup_path = path.with_suffix(f"{path.suffix}.bak-{stamp}")
    _ = shutil.copy2(path, backup_path)
    cleanup_old_backups(path)


def install_tokscale_model_aliases(repo_path: Path, config_dir: Path, stamp: str) -> None:
    """Merge managed aliases while preserving unrelated user settings."""
    src = repo_path / "tokscale_model_alias.json"
    dst = config_dir / "settings.json"
    try:
        aliases = json.loads(src.read_text(encoding="utf-8"))
        if not isinstance(aliases, dict) or not all(
            isinstance(key, str) and key.strip()
            and isinstance(value, str) and value.strip()
            for key, value in aliases.items()
        ):
            raise ValueError("Model aliases must be a non-empty-string mapping")
        settings = json.loads(dst.read_text(encoding="utf-8")) if dst.exists() else {}
        if not isinstance(settings, dict):
            raise ValueError("Tokscale settings must be a JSON object")
        existing = settings.get("modelAliases", {})
        if not isinstance(existing, dict):
            raise ValueError("Existing modelAliases must be a JSON object")
        merged = {**existing, **aliases}
        if existing == merged and "modelAliases" in settings:
            info("Tokscale model aliases already configured; skip")
            return
        settings["modelAliases"] = merged
        content = json.dumps(settings, indent=2, ensure_ascii=False) + "\n"
    except (OSError, ValueError) as exc:
        warn(f"Failed to load Tokscale aliases/settings ({type(exc).__name__}); leaving settings unchanged")
        return

    config_dir.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        info(f"Updating {dst}; preserving unrelated settings (backup enabled: {not NO_BACKUP})")
    backup_file_if_exists(dst, stamp)
    _ = dst.write_text(content, encoding="utf-8")
    success(f"Configured Tokscale model aliases: {dst}")


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


def backup_and_install_omp_models(
    src: Path, dst: Path, stamp: str, oauth: bool = False
) -> None:
    """Install native discovery or the configured gateway model catalog."""
    if oauth:
        install_rendered_text("providers: {}\n", dst, stamp)
        return
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


def find_toml_key_assignment_end_idx(lines: list[str], start_idx: int, key: str) -> int:
    key_pattern = re.compile(rf"^\s*{re.escape(key)}\s*=(.*)$")
    match = key_pattern.match(lines[start_idx])
    if match is None:
        return start_idx + 1

    value_lines = [match.group(1)]
    for end_idx in range(start_idx + 1, len(lines) + 1):
        candidate = f"{key} = " + "\n".join(value_lines) + "\n"
        try:
            _ = tomllib.loads(candidate)
            return end_idx
        except tomllib.TOMLDecodeError:
            if end_idx == len(lines):
                return end_idx
            value_lines.append(lines[end_idx])
    return len(lines)


def find_toml_key_assignment_ranges(lines: list[str], key: str) -> list[tuple[int, int]]:
    key_pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    ranges: list[tuple[int, int]] = []
    idx = 0
    while idx < len(lines):
        if key_pattern.match(lines[idx]):
            end_idx = find_toml_key_assignment_end_idx(lines, idx, key)
            ranges.append((idx, end_idx))
            idx = end_idx
            continue
        idx += 1
    return ranges


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


def ensure_codex_oauth_provider_config(lines: list[str]) -> list[str]:
    """Comment the managed top-level gateway selector; preserve other settings."""
    end = find_first_toml_section_idx(lines)
    if end is None:
        end = len(lines)
    result = list(lines)
    for idx in range(end):
        if re.match(r"^\s*model_provider\s*=", lines[idx]):
            if tomllib.loads(lines[idx]).get("model_provider") == "codex_api":
                result[idx] = "# " + lines[idx]
    return result


def ensure_codex_api_provider_config(lines: list[str]) -> list[str]:
    codex_base_url = os.environ.get("CODEX_BASE_URL", "").strip()
    if not codex_base_url:
        warn("CODEX_BASE_URL is not set; skip Codex model provider config in config.toml.")
        return lines

    # Reuse a commented gateway selector so repeated switches do not add lines.
    first_section = find_first_toml_section_idx(lines)
    end = len(lines) if first_section is None else first_section
    lines = list(lines)
    for idx in range(end):
        match = re.match(r"^\s*#\s*(model_provider\s*=.*)$", lines[idx])
        if match:
            try:
                value = tomllib.loads(match.group(1)).get("model_provider")
            except tomllib.TOMLDecodeError:
                continue
            if value == "codex_api":
                lines[idx] = match.group(1)
    lines = ensure_top_level_config_line(
        lines, 'model_provider = "codex_api"', "model_provider"
    )
    return replace_toml_section(
        lines,
        "model_providers.codex_api",
        [
            "[model_providers.codex_api]",
            'name = "codex_api"',
            f"base_url = {json.dumps(codex_base_url)}",
            'env_key = "CODEX_API_TOKEN"',
            'wire_api = "responses"',
        ],
    )


def ensure_codex_notify_config_lines(lines: list[str], codex_dir: Path) -> list[str]:
    python_bin = sys.executable or "python3"
    script_path = codex_dir / "codex-gotify-notify.py"
    desired_line = f'notify = ["{python_bin}", "{script_path}"]'
    first_section_idx = find_first_toml_section_idx(lines)
    notify_ranges = find_toml_key_assignment_ranges(lines, "notify")

    if notify_ranges:
        new_lines: list[str] = []
        wrote_top_notify = False
        idx = 0
        for start_idx, end_idx in notify_ranges:
            new_lines.extend(lines[idx:start_idx])
            is_top_level = first_section_idx is None or start_idx < first_section_idx
            if is_top_level and not wrote_top_notify:
                new_lines.append(desired_line)
                wrote_top_notify = True
            idx = end_idx
        new_lines.extend(lines[idx:])

        if not wrote_top_notify:
            insert_idx = find_first_toml_section_idx(new_lines)
            if insert_idx is None:
                insert_idx = len(new_lines)
            new_lines.insert(insert_idx, desired_line)
        return new_lines

    insert_idx = first_section_idx if first_section_idx is not None else len(lines)
    return [*lines[:insert_idx], desired_line, *lines[insert_idx:]]


def ensure_codex_config(codex_dir: Path, stamp: str, oauth: bool = False) -> None:
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
    new_lines = (ensure_codex_oauth_provider_config(new_lines) if oauth
                 else ensure_codex_api_provider_config(new_lines))

    if new_lines == lines:
        info("Codex config already configured; skip")
        return

    backup_file_if_exists(config_path, stamp)
    _ = config_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    success(f"Configured Codex config: {config_path}")


WAKATIME_MARKETPLACE = "wakatime"
WAKATIME_MARKETPLACE_SOURCE = "wakatime/codex-cli-wakatime"
WAKATIME_MARKETPLACE_GIT_URL = "https://github.com/wakatime/codex-cli-wakatime.git"
WAKATIME_PLUGIN_ID = f"codex-cli-wakatime@{WAKATIME_MARKETPLACE}"
CLAUDE_WAKATIME_MARKETPLACE_SOURCE = "wakatime/claude-code-wakatime"
CLAUDE_WAKATIME_MARKETPLACE_GIT_URL = "https://github.com/wakatime/claude-code-wakatime.git"
CLAUDE_WAKATIME_PLUGIN_ID = f"claude-code-wakatime@{WAKATIME_MARKETPLACE}"
PLUGIN_COMMAND_TIMEOUT = 300


def get_wakatime_config_path() -> Path:
    """WakaTime reads ~/.wakatime.cfg unless WAKATIME_HOME redirects it."""
    wakatime_home = os.environ.get("WAKATIME_HOME", "").strip()
    if wakatime_home:
        return Path(wakatime_home).expanduser() / ".wakatime.cfg"
    return Path.home() / ".wakatime.cfg"


def run_plugin_process(
    command: list[str], env_var: str, config_dir: Path
) -> subprocess.CompletedProcess[str] | None:
    """Run an agent CLI command with its config directory pinned to the installer's."""
    env = {**os.environ, env_var: str(config_dir)}
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            env=env,
            stdin=subprocess.DEVNULL,
            timeout=PLUGIN_COMMAND_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        warn(f"Failed to run {' '.join(command)}: {exc}")
        return None
    if result.returncode != 0:
        # Command output may contain tokens or local paths, so it is not printed.
        warn(f"{' '.join(command)} failed with exit code {result.returncode}")
        return None
    return result


def run_plugin_command(command: list[str], env_var: str, config_dir: Path) -> bool:
    """Run a plugin command whose success is reported only by its exit code."""
    return run_plugin_process(command, env_var, config_dir) is not None


def read_plugin_json(command: list[str], env_var: str, config_dir: Path) -> object | None:
    """Run a plugin command that prints JSON and return the parsed document."""
    result = run_plugin_process(command, env_var, config_dir)
    if result is None:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        warn(f"Failed to parse JSON output of {' '.join(command)}")
        return None


def run_codex_plugin_command(args: list[str], codex_dir: Path) -> dict | None:
    """Run a codex plugin subcommand under the installer's Codex home."""
    document = read_plugin_json(["codex", *args, "--json"], "CODEX_HOME", codex_dir)
    return document if isinstance(document, dict) else None


def is_codex_wakatime_plugin_installed(codex_dir: Path) -> bool:
    document = run_codex_plugin_command(
        ["plugin", "list", "--marketplace", WAKATIME_MARKETPLACE], codex_dir
    )
    if document is None:
        return False
    for entry in document.get("installed", []):
        if not isinstance(entry, dict) or entry.get("pluginId") != WAKATIME_PLUGIN_ID:
            continue
        if not entry.get("installed"):
            return False
        if not entry.get("enabled"):
            # Respect a deliberate opt-out instead of re-enabling it on every run.
            warn(f'{WAKATIME_PLUGIN_ID} is disabled; set enabled = true in config.toml')
        return True
    return False


def ensure_codex_wakatime_marketplace(codex_dir: Path) -> bool:
    """Add the WakaTime marketplace, without replacing a differently sourced one."""
    document = run_codex_plugin_command(["plugin", "marketplace", "list"], codex_dir)
    if document is not None:
        for entry in document.get("marketplaces", []):
            if not isinstance(entry, dict) or entry.get("name") != WAKATIME_MARKETPLACE:
                continue
            source = (entry.get("marketplaceSource") or {}).get("source", "")
            if source == WAKATIME_MARKETPLACE_GIT_URL:
                return True
            warn(
                f"Codex marketplace '{WAKATIME_MARKETPLACE}' uses another source; "
                "skip WakaTime plugin"
            )
            return False
    if not run_plugin_command(
        ["codex", "plugin", "marketplace", "add", WAKATIME_MARKETPLACE_SOURCE, "--json"],
        "CODEX_HOME",
        codex_dir,
    ):
        # Codex also keeps marketplace state under .tmp/marketplaces, so a stale
        # root fails the add without showing up in the marketplace listing.
        warn(f"Stale marketplace state? Try: codex plugin marketplace remove {WAKATIME_MARKETPLACE}")
        return False
    return True


def ensure_codex_wakatime_plugin(codex_dir: Path) -> bool:
    """Install the WakaTime plugin; Codex owns the marketplace and plugin state."""
    if shutil.which("codex") is None:
        warn("codex not found on PATH; skip Codex WakaTime plugin")
        return False

    if is_codex_wakatime_plugin_installed(codex_dir):
        info("Codex WakaTime plugin already installed; skip")
        return True

    if not ensure_codex_wakatime_marketplace(codex_dir):
        return False
    if run_codex_plugin_command(["plugin", "add", WAKATIME_PLUGIN_ID], codex_dir) is None:
        return False
    success(f"Installed Codex plugin: {WAKATIME_PLUGIN_ID}")
    info("Approve the plugin hooks in the next Codex session to start tracking.")
    return True


def is_claude_wakatime_plugin_installed(claude_config_dir: Path) -> bool:
    document = read_plugin_json(
        ["claude", "plugin", "list", "--json"], "CLAUDE_CONFIG_DIR", claude_config_dir
    )
    if not isinstance(document, list):
        return False
    for entry in document:
        if not isinstance(entry, dict) or entry.get("id") != CLAUDE_WAKATIME_PLUGIN_ID:
            continue
        if not entry.get("enabled"):
            # Respect a deliberate opt-out instead of re-enabling it on every run.
            warn(f"{CLAUDE_WAKATIME_PLUGIN_ID} is disabled; run: "
                 f"claude plugin enable {CLAUDE_WAKATIME_PLUGIN_ID}")
        return True
    return False


def ensure_claude_wakatime_marketplace(claude_config_dir: Path) -> bool:
    """Add the WakaTime marketplace, without replacing a differently sourced one."""
    document = read_plugin_json(
        ["claude", "plugin", "marketplace", "list", "--json"],
        "CLAUDE_CONFIG_DIR",
        claude_config_dir,
    )
    if isinstance(document, list):
        for entry in document:
            if not isinstance(entry, dict) or entry.get("name") != WAKATIME_MARKETPLACE:
                continue
            # Claude Code reports either the GitHub shorthand or the clone URL.
            if entry.get("repo") == CLAUDE_WAKATIME_MARKETPLACE_SOURCE or \
                    entry.get("url") == CLAUDE_WAKATIME_MARKETPLACE_GIT_URL:
                return True
            warn(
                f"Claude Code marketplace '{WAKATIME_MARKETPLACE}' uses another source; "
                "skip WakaTime plugin"
            )
            return False
    # This subcommand has no JSON output, so only its exit code is checked.
    return run_plugin_command(
        ["claude", "plugin", "marketplace", "add", CLAUDE_WAKATIME_MARKETPLACE_SOURCE],
        "CLAUDE_CONFIG_DIR",
        claude_config_dir,
    )


def ensure_claude_wakatime_plugin(claude_config_dir: Path) -> bool:
    """Install the WakaTime plugin; Claude Code owns the marketplace and plugin state."""
    if shutil.which("claude") is None:
        warn("claude not found on PATH; skip Claude Code WakaTime plugin")
        return False

    if is_claude_wakatime_plugin_installed(claude_config_dir):
        info("Claude Code WakaTime plugin already installed; skip")
        return True

    if not ensure_claude_wakatime_marketplace(claude_config_dir):
        return False
    # No -y: a marketplace that starts declaring an install command should stop
    # the installer instead of running that command unattended.
    document = read_plugin_json(
        ["claude", "plugin", "install", CLAUDE_WAKATIME_PLUGIN_ID, "--json"],
        "CLAUDE_CONFIG_DIR",
        claude_config_dir,
    )
    if not isinstance(document, dict) or document.get("outcome") != "ok":
        warn(f"Failed to install {CLAUDE_WAKATIME_PLUGIN_ID}")
        return False
    success(f"Installed Claude Code plugin: {CLAUDE_WAKATIME_PLUGIN_ID}")
    info("Restart Claude Code to load the plugin hooks.")
    return True


def ensure_wakatime_plugins(codex_dir: Path, claude_config_dir: Path) -> None:
    """Install the WakaTime plugins; each agent CLI owns its own plugin state."""
    installed = [
        ensure_codex_wakatime_plugin(codex_dir),
        ensure_claude_wakatime_plugin(claude_config_dir),
    ]
    if not any(installed):
        return

    if shutil.which("node") is None:
        warn("node not found on PATH; the WakaTime plugin hooks require it")

    wakatime_config = get_wakatime_config_path()
    if not wakatime_config.is_file():
        warn(f"WakaTime config not found: {wakatime_config}; add your api_key there")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync agent configurations from GitHub.")
    parser.add_argument("--oauth", action="store_true",
                        help="Use native OpenAI OAuth routing; log in separately in each agent.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None):
    args = parse_args(argv)
    print(BANNER)
    warn_missing_required_env_vars(oauth=args.oauth)

    config_dir = get_config_dir()
    omo_dir = Path.home() / ".omo"
    codex_dir = get_codex_dir()
    claude_config_dir = get_claude_config_dir()
    omp_agent_dir = get_omp_agent_dir()
    stamp = timestamp()

    repo_url = f"https://github.com/{REPO_OWNER}/{REPO_NAME}.git"

    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        repo_path = tmp_path / REPO_NAME

        info(f"[1/10] Cloning repository (branch/tag: {REPO_REV})...")
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

        for required_name in ("opencode.jsonc", "omo.jsonc"):
            if not (repo_path / required_name).is_file():
                error(f"Required repository file is missing: {required_name}")
                sys.exit(1)

        config_dir.mkdir(parents=True, exist_ok=True)
        omo_dir.mkdir(parents=True, exist_ok=True)
        codex_dir.mkdir(parents=True, exist_ok=True)
        claude_config_dir.mkdir(parents=True, exist_ok=True)
        omp_agent_dir.mkdir(parents=True, exist_ok=True)

        info(f"[2/10] Installing OpenCode config files to: {config_dir}")
        install_opencode_config_files(repo_path, config_dir, stamp, oauth=args.oauth)
        rename_path_if_exists(config_dir / "opencode.json", stamp)

        info(f"[3/10] Installing unified OMO config to: {omo_dir}")
        install_omo_config(repo_path, omo_dir, stamp, oauth=args.oauth)
        retire_legacy_openagent_files(config_dir, stamp)
        retire_legacy_omo_files(omo_dir, stamp)

        info("[4/10] Installing OpenCode plugins and skills...")
        for dir_name in ["plugins", "skills"]:
            src_dir = repo_path / dir_name
            dst_dir = config_dir / dir_name
            if src_dir.exists():
                print(f"         - {dir_name}/ (replace managed items)")
                copy_directory_items_replace(src_dir, dst_dir)

        info(f"[5/10] Installing oh-my-pi config files to: {omp_agent_dir}")
        omp_config_files = [
            ("omp_config.yml", "config.yml"),
        ]
        for src_name, dst_name in omp_config_files:
            src = repo_path / src_name
            dst = omp_agent_dir / dst_name
            if src.exists():
                print(f"         - {src_name}")
                install_omp_config(src, dst, stamp, oauth=args.oauth)

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
            print("         - models.yml (native discovery)" if args.oauth
                  else "         - omp_models.yaml (render CODEX_BASE_URL)")
            backup_and_install_omp_models(omp_models_src, omp_models_dst, stamp, oauth=args.oauth)

        info(f"[6/10] Installing shared Codex assets to: {codex_dir}")
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

        info("[7/10] Configuring Codex config")
        ensure_codex_config(codex_dir, stamp, oauth=args.oauth)

        info("[8/10] Installing WakaTime plugins for Codex and Claude Code")
        ensure_wakatime_plugins(codex_dir, claude_config_dir)

        info(f"[9/10] Installing Claude Code plugin to: {claude_config_dir}")
        install_claude_plugin(repo_path, claude_config_dir, stamp)

        info(f"[10/10] Configuring Tokscale model aliases")
        install_tokscale_model_aliases(repo_path, get_tokscale_config_dir(), stamp)

    print()
    success("Installation complete!")
    if args.oauth:
        info("OAuth routing installed; model IDs and reasoning levels are unchanged.")
        info("Log in with codex login, opencode auth login --provider openai, and OMP /login openai-codex.")
        info("Check each agent's model list. Existing profiles, explicit model choices, and resumed sessions may override defaults.")
    info(f"Timestamp: {stamp}")
    if not NO_BACKUP:
        info(f"Backups: *.bak-{stamp} (keep last {MAX_BACKUPS} per file)")


if __name__ == "__main__":
    main()
