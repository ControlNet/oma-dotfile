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
  OMO_CODING_AGENT_DIR=<OMO Native override for ~/.omo/agent; SENPI_CODING_AGENT_DIR and
                        PI_CODING_AGENT_DIR follow, matching omo's own lookup>
  TOKSCALE_CONFIG_DIR=<optional override for tokscale settings directory>
  WAKATIME_HOME=<optional override for the .wakatime.cfg location>
  WAKATIME_API_URL, WAKATIME_API_KEY=<optional; written to [settings] api_url/api_key in
                        .wakatime.cfg. WAKATIME_API_URL is read only by this installer>
  INSTALL_ALL=1 (optional; install every target without detecting agents)
  NO_BACKUP=1 (optional; changed config files are otherwise kept as *.bak-<stamp>.
              Repo-managed plugin code is replaced without backups.)
"""

import argparse
import filecmp
import json
import os
import re
import shutil
import sys
import subprocess
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11; fall back to the small scanners below.
    tomllib = None

# Config from environment
REPO_OWNER = os.environ.get("REPO_OWNER", "ControlNet")
REPO_NAME = os.environ.get("REPO_NAME", "oma-dotfile")
REPO_REV = os.environ.get("REPO_REV", "master")
CONFIG_DIR_ENV = os.environ.get("CONFIG_DIR", "")
CODEX_DIR_ENV = os.environ.get("CODEX_DIR", "")
CLAUDE_CONFIG_DIR_ENV = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
OMP_AGENT_DIR_ENV = os.environ.get("OMP_AGENT_DIR", "").strip()
NO_BACKUP = os.environ.get("NO_BACKUP", "0") == "1"
INSTALL_ALL = os.environ.get("INSTALL_ALL", "0") == "1"
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
    # Flush first: stdout is block-buffered when piped, stderr is not, so without
    # this a warning overtakes the line it belongs to.
    sys.stdout.flush()
    print(f"{YELLOW}{BOLD}[WARN]{RESET}    {msg}", file=sys.stderr, flush=True)


def error(msg: str) -> None:
    """Print error message with red color and exit."""
    sys.stdout.flush()
    print(f"{RED}{BOLD}[ERROR]{RESET}   {msg}", file=sys.stderr, flush=True)


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


def get_omo_dir() -> Path:
    """Determine the OMO configuration directory."""
    return Path.home() / ".omo"


# omo-ai bin/lib/agent-dir.js AGENT_DIR_ENV_NAMES, most specific first.
OMO_AGENT_DIR_ENV_NAMES = ("OMO_CODING_AGENT_DIR", "SENPI_CODING_AGENT_DIR", "PI_CODING_AGENT_DIR")


def get_omo_agent_dir() -> Path:
    """Determine the OMO Native engine state directory the way omo itself does."""
    for name in OMO_AGENT_DIR_ENV_NAMES:
        configured = os.environ.get(name, "").strip()
        if configured:
            return Path(configured).expanduser()
    return get_omo_dir() / "agent"


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


# Targets are reported in this order. The OMO OpenCode plugin has no executable of its
# own, so the OpenCode target gates its config; OMO Native ships the `omo` CLI.
TARGET_LABELS = {
    "opencode": "OpenCode/OMO",
    "omo": "OMO Native",
    "omp": "oh-my-pi",
    "codex": "Codex",
    "claude": "Claude Code",
    "tokscale": "Tokscale",
}

AGENT_EXECUTABLES = {
    "opencode": "opencode",
    "omo": "omo",
    "omp": "omp",
    "codex": "codex",
    "claude": "claude",
    "tokscale": "",  # Ships no CLI; detected from its configuration directory.
}

# Interactive shells add these; `curl ... | python3 -` often does not.
EXTRA_BIN_DIRS = (".opencode/bin", ".bun/bin", ".local/bin", ".npm-global/bin")


def extra_bin_search_path() -> str:
    """Build a PATH of per-user bin directories a non-interactive shell may omit."""
    home = Path.home()
    directories = [home / relative for relative in EXTRA_BIN_DIRS]
    # Newest node first, as a fresh nvm shell would use: an old version can still hold a
    # stale CLI (an old codex has no `plugin` command), and string order puts v9 after v10.
    directories.extend(sorted((home / ".nvm" / "versions" / "node").glob("*/bin"),
                              key=lambda path: nvm_version_key(path.parent.name), reverse=True))
    return os.pathsep.join(str(directory) for directory in directories)


def nvm_version_key(name: str) -> tuple[int, ...]:
    """Sort key for nvm dirs like `v24.11.1`; unparsable names sort last."""
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", name)
    return tuple(int(part) for part in match.groups()) if match else (-1,)


def find_agent_executable(name: str) -> Path | None:
    """Resolve an agent CLI from PATH, then from known per-user install locations."""
    if not name:
        return None
    found = shutil.which(name) or shutil.which(name, path=extra_bin_search_path())
    return Path(found) if found else None


def detect_targets(force: bool = False) -> dict[str, bool]:
    """Report which agent software is present so only its config gets installed."""
    detected = {}
    for name in TARGET_LABELS:
        if force:
            detected[name] = True
        elif name == "tokscale":
            detected[name] = get_tokscale_config_dir().is_dir()
        else:
            detected[name] = find_agent_executable(AGENT_EXECUTABLES[name]) is not None
    return detected


def report_targets(targets: dict[str, bool], forced: bool = False) -> None:
    """Show which agents were detected and which are skipped as not installed."""
    if forced:
        info("Installing every target without detection (--all)")
        return
    found = [TARGET_LABELS[name] for name, enabled in targets.items() if enabled]
    missing = [TARGET_LABELS[name] for name, enabled in targets.items() if not enabled]
    info(f"Detected: {', '.join(found)}" if found else "Detected: nothing")
    if missing:
        warn(f"Not installed, skipping: {', '.join(missing)}")
        info("Use --all (or INSTALL_ALL=1) to install these anyway.")


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
    # Order by the fixed-width stamp in the name: copy2 keeps the source's mtime, so a
    # config restored with an old mtime would otherwise make the newest backup look oldest.
    backups = sorted(file_path.parent.glob(pattern), key=lambda p: p.name)
    while len(backups) > MAX_BACKUPS:
        oldest = backups.pop(0)
        oldest.unlink()
        info(f"Removed old backup: {oldest.name}")


def backup_and_install(src: Path, dst: Path, stamp: str) -> None:
    """Install user-editable config, backing up the previous copy only when it changes."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_file() and filecmp.cmp(src, dst, shallow=False):
        return
    if not NO_BACKUP and dst.exists():
        backup_path = dst.with_suffix(f"{dst.suffix}.bak-{stamp}")
        _ = shutil.copy2(dst, backup_path)
        cleanup_old_backups(dst)
    _ = shutil.copy2(src, dst)


def install_managed_file(src: Path, dst: Path) -> None:
    """Install repo-managed plugin code without backups; git history already keeps old versions."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_file() and filecmp.cmp(src, dst, shallow=False):
        return
    _ = shutil.copy2(src, dst)


def prepare_target_dir(path: Path) -> Path:
    """Create a target directory only once its agent has been detected."""
    path.mkdir(parents=True, exist_ok=True)
    return path


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


JSONC_STRUCTURE_TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/|[{}]', re.DOTALL)


def find_jsonc_top_level_object(content: str, key: str) -> tuple[int, int] | None:
    """Return the span of a top-level member's object value, skipping strings and comments."""
    quoted_key = json.dumps(key)
    depth = 0
    armed = False
    start = None
    for match in JSONC_STRUCTURE_TOKEN.finditer(content):
        token = match.group()
        if token == "{":
            depth += 1
            if armed and depth == 2:
                start, armed = match.start(), False
        elif token == "}":
            depth -= 1
            if start is not None and depth == 1:
                return start, match.end()
        elif depth == 1 and start is None:
            armed = token == quoted_key
    return None


def rewrite_model_prefix(content: str, prefix: str) -> str:
    """Point every `"codex/<model>"` string at another provider, keeping the model ids."""
    return JSONC_TOKEN.sub(
        lambda match: match.group().replace('"codex/', f'"{prefix}/', 1)
        if match.group().startswith('"codex/') else match.group(),
        content,
    )


def render_omo_oauth_config(content: str) -> str:
    """OpenCode reaches ChatGPT OAuth as `openai/`; OMO Native calls it `chatgpt-subscription/`."""
    native = find_jsonc_top_level_object(content, "[native]")
    if native is None:
        return rewrite_model_prefix(content, "openai")
    start, end = native
    return (rewrite_model_prefix(content[:start], "openai")
            + rewrite_model_prefix(content[start:end], "chatgpt-subscription")
            + rewrite_model_prefix(content[end:], "openai"))


def install_omo_config(
    repo_path: Path, omo_dir: Path, stamp: str, oauth: bool = False
) -> None:
    src = repo_path / "omo.jsonc"
    print("         - omo.jsonc")
    if oauth:
        content = render_omo_oauth_config(src.read_text(encoding="utf-8"))
        install_rendered_text(content, omo_dir / "omo.jsonc", stamp)
    else:
        backup_and_install(src, omo_dir / "omo.jsonc", stamp)


# OpenCode reasoning variants that OMO Native only offers once a model maps them explicitly.
OMO_NATIVE_THINKING_LEVELS = ("low", "medium", "high", "xhigh", "max")


def build_omo_native_gateway_provider(repo_path: Path, codex_base_url: str) -> dict:
    """Mirror OpenCode's `codex` gateway provider in OMO Native's models.json shape."""
    opencode = read_jsonc_object(repo_path / "opencode.jsonc")
    models = []
    for model_id, entry in opencode["provider"]["codex"]["models"].items():
        limit = entry.get("limit", {})
        cost = entry.get("cost", {})
        variants = entry.get("variants", {})
        models.append({
            "id": model_id,
            "reasoning": bool(entry.get("reasoning")),
            "input": entry.get("modalities", {}).get("input", ["text"]),
            # A separate input cap is what the gateway enforces, as omp_models.yaml records.
            "contextWindow": limit.get("input", limit.get("context")),
            "maxTokens": limit.get("output"),
            "cost": {
                "input": cost.get("input", 0),
                "output": cost.get("output", 0),
                "cacheRead": cost.get("cache_read", 0),
                "cacheWrite": cost.get("cache_write", 0),
            },
            "thinkingLevelMap": {
                level: variants[level].get("reasoningEffort", level)
                for level in OMO_NATIVE_THINKING_LEVELS if level in variants
            },
        })
    return {
        # The engine sends baseUrl verbatim; only apiKey and headers are interpolated.
        "baseUrl": codex_base_url,
        "api": "openai-responses",
        "apiKey": "${CODEX_API_TOKEN}",
        "models": models,
    }


def install_omo_native_models(
    repo_path: Path, agent_dir: Path, stamp: str, oauth: bool = False
) -> None:
    """Register the gateway as the `codex` provider, preserving unrelated providers."""
    if oauth:
        info("         OAuth mode: models.json unchanged; ChatGPT is the built-in chatgpt-subscription provider")
        return
    codex_base_url = os.environ.get("CODEX_BASE_URL", "").strip()
    if not codex_base_url:
        warn("CODEX_BASE_URL is not set; skipping OMO Native models.json, so codex/ models stay unavailable")
        return
    dst = agent_dir / "models.json"
    try:
        document = read_jsonc_object(dst) if dst.exists() else {}
        providers = document.setdefault("providers", {})
        if not isinstance(providers, dict):
            raise ValueError("providers must be a JSON object")
        providers["codex"] = build_omo_native_gateway_provider(repo_path, codex_base_url)
    except (OSError, ValueError, KeyError) as exc:
        warn(f"Failed to update {dst} ({type(exc).__name__}); leaving models.json unchanged")
        return
    print("         - models.json (codex gateway provider, render CODEX_BASE_URL)")
    install_rendered_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", dst, stamp)


def ensure_omo_native_settings(agent_dir: Path, stamp: str) -> None:
    """Disable the builtin rules extension, which reads ~/.claude rules and CLAUDE.md."""
    if (agent_dir / "settings.jsonc").exists():
        warn(f"{agent_dir / 'settings.jsonc'} takes precedence over settings.json; "
             'add "rules" to its disabledBuiltinExtensions by hand')
        return
    dst = agent_dir / "settings.json"
    try:
        settings = read_jsonc_object(dst) if dst.exists() else {}
        disabled = settings.get("disabledBuiltinExtensions", [])
        if not isinstance(disabled, list):
            raise ValueError("disabledBuiltinExtensions must be a list")
    except (OSError, ValueError) as exc:
        warn(f"Failed to read {dst} ({type(exc).__name__}); leaving settings.json unchanged")
        return
    if "rules" in disabled:
        return
    settings["disabledBuiltinExtensions"] = [*disabled, "rules"]
    print("         - settings.json (disable builtin rules extension)")
    install_rendered_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", dst, stamp)


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
    """Install native OAuth overrides or the configured gateway model catalog."""
    if oauth:
        oauth_src = src.with_name("omp_models_oauth.yaml")
        try:
            content = oauth_src.read_text(encoding="utf-8")
        except OSError as exc:
            warn(f"Failed to read {oauth_src}: {exc}")
            return
        install_rendered_text(content, dst, stamp)
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

    try:
        install_rendered_text(content, dst, stamp)
    except OSError as exc:
        warn(f"Failed to write {dst}: {exc}")


# One bare or quoted key part; dotted keys join them with optional spaces.
TOML_KEY_PART = r"""(?:[A-Za-z0-9_-]+|"(?:[^"\\]|\\.)*"|'[^']*')"""
TOML_DOTTED_KEY = rf"{TOML_KEY_PART}(?:\s*\.\s*{TOML_KEY_PART})*"
# A header may carry a trailing comment: `[profiles.work] # note` is valid TOML.
TOML_TABLE_HEADER = re.compile(rf"^\s*\[\[?\s*({TOML_DOTTED_KEY})\s*\]\]?\s*(?:#.*)?$")
TOML_ASSIGNMENT_START = re.compile(rf"^\s*({TOML_DOTTED_KEY})\s*=(.*)$")


def toml_key_name(raw: str) -> str:
    """Normalize a dotted key so `a . "b"` and `a.b` compare equal."""
    parts = []
    for part in re.findall(TOML_KEY_PART, raw):
        if part.startswith('"'):
            try:
                part = json.loads(part)
            except ValueError:
                part = part[1:-1]
        elif part.startswith("'"):
            part = part[1:-1]
        parts.append(part)
    return ".".join(parts)


def toml_table_name(line: str) -> str | None:
    """Return the name of a `[table]` header line; array tables do not count."""
    match = TOML_TABLE_HEADER.match(line)
    if match is None or line.lstrip().startswith("[["):
        return None
    return toml_key_name(match.group(1))


def toml_statement_starts(lines: list[str]) -> list[int]:
    """Indexes of lines that begin a statement; lines inside multiline values are skipped."""
    starts: list[int] = []
    idx = 0
    while idx < len(lines):
        starts.append(idx)
        match = TOML_ASSIGNMENT_START.match(lines[idx])
        idx = toml_value_end_idx(lines, idx, match.group(1), match.group(2)) if match else idx + 1
    return starts


def find_first_toml_section_idx(lines: list[str]) -> int | None:
    return next((idx for idx in toml_statement_starts(lines)
                 if TOML_TABLE_HEADER.match(lines[idx])), None)


def ensure_top_level_config_line(lines: list[str], desired_line: str, key: str) -> list[str]:
    first_section_idx = find_first_toml_section_idx(lines)
    top_level_ranges = [
        (start, end) for start, end in find_toml_key_assignment_ranges(lines, key)
        if first_section_idx is None or start < first_section_idx
    ]

    if top_level_ranges:
        # Drop whole assignments, so a multiline value leaves no continuation lines behind.
        matching_set = {idx for start, end in top_level_ranges for idx in range(start, end)}
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


TOML_STRING_ASSIGNMENT = re.compile(
    rf"""^\s*({TOML_DOTTED_KEY})\s*=\s*(?:"((?:[^"\\]|\\.)*)"|'([^']*)')\s*(?:#.*)?$"""
)


def is_escaped(value: str, idx: int) -> bool:
    backslashes = 0
    while idx - backslashes > 0 and value[idx - backslashes - 1] == "\\":
        backslashes += 1
    return backslashes % 2 == 1


def toml_value_is_complete(value: str) -> bool:
    """Return whether brackets and strings in a TOML value are balanced."""
    depth = 0
    seen_value = False
    idx = 0
    while idx < len(value):
        char = value[idx]
        if char == "#":
            newline = value.find("\n", idx)
            if newline == -1:
                break
            idx = newline + 1
            continue
        if char in "\"'":
            quote = char * 3 if value.startswith(char * 3, idx) else char
            end = value.find(quote, idx + len(quote))
            # Only basic strings support escapes; skip quotes after an odd backslash run.
            while char == '"' and end != -1 and is_escaped(value, end):
                end = value.find(quote, end + 1)
            if end == -1:
                return False
            if len(quote) == 3:
                # Up to two content quotes may sit right before the closing delimiter, so
                # `"""a""""` closes at its last three quotes.
                extra = 0
                while extra < 2 and value.startswith(char, end + 3 + extra):
                    extra += 1
                end += extra
            seen_value = True
            idx = end + len(quote)
            continue
        if char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
        if not char.isspace():
            seen_value = True
        idx += 1
    return seen_value and depth <= 0


def toml_assignment_is_complete(key: str, value: str) -> bool:
    if tomllib is not None:
        try:
            _ = tomllib.loads(f"{key} = {value}\n")
        except tomllib.TOMLDecodeError:
            pass
        else:
            return True
    # Balanced brackets and quotes also end a value tomllib rejects (a typo, or a
    # TOML 1.1 multiline inline table), instead of swallowing the rest of the file.
    return toml_value_is_complete(value)


def read_toml_string_assignment(text: str, key: str) -> str | None:
    """Return the string value of a `key = "..."` assignment; the fallback reads one line."""
    if tomllib is not None:
        try:
            value = tomllib.loads(text).get(key)
        except tomllib.TOMLDecodeError:
            return None
        return value if isinstance(value, str) else None
    match = TOML_STRING_ASSIGNMENT.match(text)
    if match is None or toml_key_name(match.group(1)) != key:
        return None
    if match.group(3) is not None:
        return match.group(3)
    try:
        return json.loads(f'"{match.group(2)}"')
    except ValueError:
        return None


def toml_value_end_idx(lines: list[str], start_idx: int, key: str, first_value: str) -> int:
    """Return the index after the last line of the value that starts on `start_idx`."""
    value_lines = [first_value]
    for end_idx in range(start_idx + 1, len(lines) + 1):
        if toml_assignment_is_complete(key, "\n".join(value_lines)):
            return end_idx
        if end_idx == len(lines):
            return end_idx
        value_lines.append(lines[end_idx])
    return len(lines)


def find_toml_key_assignment_end_idx(lines: list[str], start_idx: int, key: str) -> int:
    match = TOML_ASSIGNMENT_START.match(lines[start_idx])
    if match is None or toml_key_name(match.group(1)) != key:
        return start_idx + 1
    return toml_value_end_idx(lines, start_idx, match.group(1), match.group(2))


def find_toml_key_assignment_ranges(lines: list[str], key: str) -> list[tuple[int, int]]:
    starts = toml_statement_starts(lines)
    ranges: list[tuple[int, int]] = []
    for pos, start in enumerate(starts):
        match = TOML_ASSIGNMENT_START.match(lines[start])
        if match and toml_key_name(match.group(1)) == key:
            ranges.append((start, starts[pos + 1] if pos + 1 < len(starts) else len(lines)))
    return ranges


def replace_toml_section(lines: list[str], section_name: str, section_lines: list[str]) -> list[str]:
    headers = [idx for idx in toml_statement_starts(lines) if TOML_TABLE_HEADER.match(lines[idx])]
    section_start = next((idx for idx in headers if toml_table_name(lines[idx]) == section_name), None)

    if section_start is None:
        if lines and lines[-1].strip():
            return [*lines, "", *section_lines]
        return [*lines, *section_lines]

    section_end = next((idx for idx in headers if idx > section_start), len(lines))
    return [*lines[:section_start], *section_lines, *lines[section_end:]]


def ensure_codex_oauth_provider_config(lines: list[str]) -> list[str]:
    """Comment the managed top-level gateway selector; preserve other settings."""
    end = find_first_toml_section_idx(lines)
    top_level = lines if end is None else lines[:end]
    result: list[str] = []
    idx = 0
    for start, stop in find_toml_key_assignment_ranges(top_level, "model_provider"):
        result.extend(lines[idx:start])
        assignment = lines[start:stop]
        if read_toml_string_assignment("\n".join(assignment), "model_provider") != "codex_api":
            result.extend(assignment)
        elif len(assignment) == 1:
            result.append("# " + assignment[0])
        else:
            # Collapse a multiline value into one commented line that API mode can restore.
            result.append('# model_provider = "codex_api"')
        idx = stop
    result.extend(lines[idx:])
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
    for idx in toml_statement_starts(lines[:end]):
        match = re.match(r"^\s*#\s*(.*)$", lines[idx])
        assignment = TOML_ASSIGNMENT_START.match(match.group(1)) if match else None
        if assignment and toml_key_name(assignment.group(1)) == "model_provider":
            if read_toml_string_assignment(match.group(1), "model_provider") == "codex_api":
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


def toml_basic_string(value: str) -> str:
    """Quote a TOML basic string; JSON escapes are valid TOML, unlike raw Windows backslashes."""
    # ensure_ascii=False: TOML rejects the surrogate pairs JSON uses for non-BMP characters.
    return json.dumps(value, ensure_ascii=False)


def ensure_codex_notify_config_lines(lines: list[str], codex_dir: Path) -> list[str]:
    python_bin = sys.executable or "python3"
    script_path = codex_dir / "codex-gotify-notify.py"
    desired_line = f"notify = [{toml_basic_string(python_bin)}, {toml_basic_string(str(script_path))}]"
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
# Marketplaces are added by clone URL, not by owner/repo shorthand: the shorthand
# makes the agent CLI try SSH first, which needs working GitHub SSH credentials.
WAKATIME_MARKETPLACE_GIT_URL = "https://github.com/wakatime/codex-cli-wakatime.git"
WAKATIME_MARKETPLACE_REPO = "wakatime/codex-cli-wakatime"
WAKATIME_PLUGIN_ID = f"codex-cli-wakatime@{WAKATIME_MARKETPLACE}"
CLAUDE_WAKATIME_MARKETPLACE_GIT_URL = "https://github.com/wakatime/claude-code-wakatime.git"
CLAUDE_WAKATIME_MARKETPLACE_REPO = "wakatime/claude-code-wakatime"
CLAUDE_WAKATIME_PLUGIN_ID = f"claude-code-wakatime@{WAKATIME_MARKETPLACE}"
PLUGIN_COMMAND_TIMEOUT = 300


def get_wakatime_config_path() -> Path:
    """WakaTime reads ~/.wakatime.cfg unless WAKATIME_HOME redirects it."""
    wakatime_home = os.environ.get("WAKATIME_HOME", "").strip()
    if wakatime_home:
        return Path(wakatime_home).expanduser() / ".wakatime.cfg"
    return Path.home() / ".wakatime.cfg"


# Installer env var -> [settings] key. wakatime-cli itself reads WAKATIME_API_KEY but
# has no env var for api_url, so a self-hosted server needs it written to the cfg.
WAKATIME_ENV_SETTINGS = {"WAKATIME_API_URL": "api_url", "WAKATIME_API_KEY": "api_key"}
# Spellings wakatime-cli accepts in [settings]; all are replaced by the canonical key.
WAKATIME_SETTING_ALIASES = {"api_url": ("api_url",), "api_key": ("api_key", "apikey")}


def render_wakatime_config(content: str, settings: dict[str, str]) -> str:
    """Set keys in the INI [settings] section, keeping every other line as it is."""
    lines = content.splitlines()
    start = next((idx for idx, line in enumerate(lines)
                  if line.strip().lower() == "[settings]"), None)
    if start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("[settings]")
        start = len(lines) - 1
    end = next((idx for idx in range(start + 1, len(lines))
                if lines[idx].strip().startswith("[")), len(lines))
    section = lines[start + 1:end]

    for key, value in settings.items():
        aliases = "|".join(re.escape(alias) for alias in WAKATIME_SETTING_ALIASES[key])
        pattern = re.compile(rf"^\s*(?:{aliases})\s*[=:]")
        matches = [idx for idx, line in enumerate(section) if pattern.match(line)]
        desired = f"{key} = {value}"
        if matches:
            section[matches[0]] = desired
            section = [line for idx, line in enumerate(section) if idx not in matches[1:]]
        else:
            # Insert after the last setting, before the blank lines that end the section.
            insert_idx = len(section)
            while insert_idx > 0 and not section[insert_idx - 1].strip():
                insert_idx -= 1
            section.insert(insert_idx, desired)

    return "\n".join([*lines[:start + 1], *section, *lines[end:]]) + "\n"


def ensure_wakatime_config() -> None:
    """Write WAKATIME_API_URL and WAKATIME_API_KEY into the cfg, keeping other settings."""
    path = get_wakatime_config_path()
    settings: dict[str, str] = {}
    for env_name, key in WAKATIME_ENV_SETTINGS.items():
        value = os.environ.get(env_name, "").strip()
        if not value:
            continue
        if "\n" in value or "\r" in value:
            warn(f"{env_name} contains a line break; not written to {path}")
            continue
        settings[key] = value

    if not settings:
        if not path.is_file() and not os.environ.get("WAKATIME_API_KEY", "").strip():
            warn(f"WakaTime config not found: {path}; set WAKATIME_API_KEY "
                 "(and WAKATIME_API_URL for a self-hosted server) and rerun")
        return

    try:
        content = path.read_text(encoding="utf-8") if path.is_file() else ""
        rendered = render_wakatime_config(content, settings)
        # A new file is owner-only. An existing one is made owner-only before the key is
        # written into it, or when an older run already put it there; without a key to
        # write, it keeps the mode the user chose.
        if "api_key" in settings and path.exists():
            path.chmod(0o600)
        if rendered == content:
            info(f"WakaTime config already matches the environment; skip: {path}")
            return
        # No backup: only env-sourced values change, and a backup would keep the old key.
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(rendered)
    except (OSError, UnicodeDecodeError) as exc:
        warn(f"Failed to update {path} ({type(exc).__name__}); leaving it unchanged")
        return
    # Name the keys only; their values may be secrets.
    success(f"Configured WakaTime {', '.join(settings)}: {path}")


def run_plugin_process(
    command: list[str], env_var: str, config_dir: Path
) -> subprocess.CompletedProcess[str] | None:
    """Run an agent CLI command with its config directory pinned to the installer's."""
    env = {**os.environ, env_var: str(config_dir)}
    executable = find_agent_executable(command[0])
    if executable is not None:
        # Detection also searches per-user bin dirs a piped install's PATH may lack; call
        # the CLI by path, with its dir on PATH for the `env node` shebang of npm/bun CLIs.
        command = [str(executable), *command[1:]]
        env["PATH"] = os.pathsep.join(filter(None, [str(executable.parent), env.get("PATH")]))
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
        ["codex", "plugin", "marketplace", "add", WAKATIME_MARKETPLACE_GIT_URL, "--json"],
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
    if find_agent_executable("codex") is None:
        warn("codex not found; skip Codex WakaTime plugin")
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
            # Claude Code reports either the clone URL or the GitHub shorthand,
            # depending on how the marketplace was originally added.
            if entry.get("url") == CLAUDE_WAKATIME_MARKETPLACE_GIT_URL or \
                    entry.get("repo") == CLAUDE_WAKATIME_MARKETPLACE_REPO:
                return True
            warn(
                f"Claude Code marketplace '{WAKATIME_MARKETPLACE}' uses another source; "
                "skip WakaTime plugin"
            )
            return False
    # This subcommand has no JSON output, so only its exit code is checked.
    return run_plugin_command(
        ["claude", "plugin", "marketplace", "add", CLAUDE_WAKATIME_MARKETPLACE_GIT_URL],
        "CLAUDE_CONFIG_DIR",
        claude_config_dir,
    )


def ensure_claude_wakatime_plugin(claude_config_dir: Path) -> bool:
    """Install the WakaTime plugin; Claude Code owns the marketplace and plugin state."""
    if find_agent_executable("claude") is None:
        warn("claude not found; skip Claude Code WakaTime plugin")
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


def begin_step(label: str, message: str, enabled: bool, reason: str) -> bool:
    """Announce a step and report why it is skipped; return whether to run it."""
    info(f"[{label}] {message}")
    if not enabled:
        warn(f"         skipped: {reason}")
    return enabled


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync agent configurations from GitHub.")
    parser.add_argument("--oauth", action="store_true",
                        help="Use native OpenAI OAuth routing; log in separately in each agent.")
    parser.add_argument("--all", dest="install_all", action="store_true",
                        help="Install every target even if its agent is not detected.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None):
    args = parse_args(argv)
    print(BANNER)
    warn_missing_required_env_vars(oauth=args.oauth)

    forced = args.install_all or INSTALL_ALL
    targets = detect_targets(force=forced)
    report_targets(targets, forced=forced)

    config_dir = get_config_dir()
    omo_dir = get_omo_dir()
    codex_dir = get_codex_dir()
    claude_config_dir = get_claude_config_dir()
    omp_agent_dir = get_omp_agent_dir()
    omo_agent_dir = get_omo_agent_dir()
    stamp = timestamp()

    repo_url = f"https://github.com/{REPO_OWNER}/{REPO_NAME}.git"

    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        repo_path = tmp_path / REPO_NAME

        info(f"[1/11] Cloning repository (branch/tag: {REPO_REV})...")
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

        if begin_step("2/11", f"Installing OpenCode config files to: {config_dir}",
                      targets["opencode"], "opencode not found"):
            prepare_target_dir(config_dir)
            install_opencode_config_files(repo_path, config_dir, stamp, oauth=args.oauth)
            rename_path_if_exists(config_dir / "opencode.json", stamp)
            retire_legacy_openagent_files(config_dir, stamp)

        if begin_step("3/11", f"Installing unified OMO config to: {omo_dir}",
                      targets["opencode"] or targets["omo"], "neither opencode nor omo found"):
            prepare_target_dir(omo_dir)
            install_omo_config(repo_path, omo_dir, stamp, oauth=args.oauth)
            retire_legacy_omo_files(omo_dir, stamp)

        if begin_step("4/11", f"Installing OMO Native config to: {omo_agent_dir}",
                      targets["omo"], "omo not found"):
            prepare_target_dir(omo_agent_dir)
            instructions_src = repo_path / "_AGENTS.md"
            if instructions_src.exists():
                print("         - _AGENTS.md -> AGENTS.md")
                install_rendered_text(
                    instructions_src.read_text(encoding="utf-8"),
                    omo_agent_dir / "AGENTS.md",
                    stamp,
                )
            install_omo_native_models(repo_path, omo_agent_dir, stamp, oauth=args.oauth)
            ensure_omo_native_settings(omo_agent_dir, stamp)

        if begin_step("5/11", "Installing OpenCode plugins and skills...",
                      targets["opencode"], "opencode not found"):
            prepare_target_dir(config_dir)
            for dir_name in ["plugins", "skills"]:
                src_dir = repo_path / dir_name
                dst_dir = config_dir / dir_name
                if src_dir.exists():
                    print(f"         - {dir_name}/ (replace managed items)")
                    copy_directory_items_replace(src_dir, dst_dir)

        if begin_step("6/11", f"Installing oh-my-pi config files to: {omp_agent_dir}",
                      targets["omp"], "omp not found"):
            prepare_target_dir(omp_agent_dir)
            omp_config_files = [
                ("omp_config.yml", "config.yml"),
            ]
            for src_name, dst_name in omp_config_files:
                src = repo_path / src_name
                dst = omp_agent_dir / dst_name
                if src.exists():
                    print(f"         - {src_name}")
                    install_omp_config(src, dst, stamp, oauth=args.oauth)

            # OMP loads ~/.config/opencode/AGENTS.md only when opencode is in
            # enabledProviders, which would also pull in OpenCode's plugins and MCP.
            instructions_src = repo_path / "_AGENTS.md"
            if instructions_src.exists():
                print("         - _AGENTS.md -> AGENTS.md")
                install_rendered_text(
                    instructions_src.read_text(encoding="utf-8"),
                    omp_agent_dir / "AGENTS.md",
                    stamp,
                )

            # Same reason for skills/; autolearn's managed-skills/ is a separate directory.
            omp_skills_src = repo_path / "skills"
            if omp_skills_src.exists():
                print("         - skills/ (replace managed items)")
                copy_directory_items_replace(omp_skills_src, omp_agent_dir / "skills")

            omp_extension_files = [
                ("omp-gotify-notify.js", "extensions/omp-gotify-notify.js"),
                ("omp-wakatime-sync.js", "extensions/omp-wakatime-sync.js"),
            ]
            for src_name, dst_name in omp_extension_files:
                src = repo_path / src_name
                dst = omp_agent_dir / dst_name
                if src.exists():
                    print(f"         - {src_name}")
                    install_managed_file(src, dst)

            omp_models_src = repo_path / "omp_models.yaml"
            omp_models_dst = omp_agent_dir / "models.yml"
            if omp_models_src.exists():
                print("         - omp_models_oauth.yaml (native model overrides)" if args.oauth
                      else "         - omp_models.yaml (render CODEX_BASE_URL)")
                backup_and_install_omp_models(omp_models_src, omp_models_dst, stamp, oauth=args.oauth)

        if begin_step("7/11", f"Installing shared Codex assets to: {codex_dir}",
                      targets["codex"], "codex not found"):
            prepare_target_dir(codex_dir)
            codex_agents_src = repo_path / "_AGENTS.md"
            if codex_agents_src.exists():
                print("         - _AGENTS.md")
                backup_and_install(codex_agents_src, codex_dir / "AGENTS.md", stamp)

            codex_notify_src = repo_path / "codex-gotify-notify.py"
            if codex_notify_src.exists():
                print("         - codex-gotify-notify.py")
                install_managed_file(codex_notify_src, codex_dir / "codex-gotify-notify.py")

            codex_skills_src = repo_path / "skills"
            codex_skills_dst = codex_dir / "skills"
            if codex_skills_src.exists():
                print("         - skills/ (merge)")
                copy_directory_merge(codex_skills_src, codex_skills_dst)

        if begin_step("8/11", "Configuring Codex config",
                      targets["codex"], "codex not found"):
            prepare_target_dir(codex_dir)
            ensure_codex_config(codex_dir, stamp, oauth=args.oauth)

        if begin_step("9/11", "Configuring WakaTime config and plugins",
                      targets["opencode"] or targets["omp"] or targets["codex"] or targets["claude"],
                      "no WakaTime-tracked agent found"):
            # OpenCode and OMP use the cfg too; only Codex and Claude Code need plugins.
            ensure_wakatime_config()
            if targets["codex"] or targets["claude"]:
                # Each plugin follows its own agent inside ensure_wakatime_plugins; both
                # directories are created first so neither CLI is handed a missing one.
                if targets["codex"]:
                    prepare_target_dir(codex_dir)
                if targets["claude"]:
                    prepare_target_dir(claude_config_dir)
                ensure_wakatime_plugins(codex_dir, claude_config_dir)

        if begin_step("10/11", f"Installing Claude Code assets to: {claude_config_dir}",
                      targets["claude"], "claude not found"):
            prepare_target_dir(claude_config_dir)
            instructions_src = repo_path / "_AGENTS.md"
            if instructions_src.exists():
                print("         - _AGENTS.md -> rules/oma-dotfile.md")
                install_rendered_text(
                    instructions_src.read_text(encoding="utf-8"),
                    claude_config_dir / "rules" / "oma-dotfile.md",
                    stamp,
                )
            install_claude_plugin(repo_path, claude_config_dir, stamp)

        if begin_step("11/11", "Configuring Tokscale model aliases",
                      targets["tokscale"], "tokscale config directory not found"):
            install_tokscale_model_aliases(repo_path, get_tokscale_config_dir(), stamp)

    print()
    success("Installation complete!")
    if args.oauth:
        info("OAuth routing installed; model IDs and reasoning levels are unchanged.")
        logins = []
        if targets["codex"]:
            logins.append("codex login")
        if targets["opencode"]:
            logins.append("opencode auth login --provider openai")
        if targets["omo"]:
            logins.append("omo /login chatgpt-subscription")
        if targets["omp"]:
            logins.append("OMP /login openai-codex")
        if logins:
            info(f"Log in with: {'; '.join(logins)}")
        info("Check each agent's model list. Existing profiles, explicit model choices, and resumed sessions may override defaults.")
    info(f"Timestamp: {stamp}")
    if not NO_BACKUP:
        info(f"Backups: *.bak-{stamp} (keep last {MAX_BACKUPS} per file)")


if __name__ == "__main__":
    main()
