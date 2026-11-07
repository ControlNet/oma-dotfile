"""Claude Code: the shared rules, plugins, no commit attribution, and the commit-msg hook."""

from collections.abc import Mapping
import json
from pathlib import Path
import shutil
import stat
import subprocess
import sys

from omadotfile.agents.base import Agent
from omadotfile.console import item, success, warn
from omadotfile.constants import CLAUDE_ATTRIBUTION, CLAUDE_FILES, CLAUDE_PLUGINS_DIR, COMMIT_MSG_HOOK
from omadotfile.context import Context
from omadotfile.core.files import IGNORED_NAMES


def render_plugin_hooks(hooks_path: Path) -> None:
    """Run every command hook of a plugin with this Python, which has the plugin's imports."""
    hooks_document = json.loads(hooks_path.read_text(encoding="utf-8"))
    for event_entries in hooks_document["hooks"].values():
        for event_entry in event_entries:
            for hook in event_entry["hooks"]:
                if hook.get("type") == "command":
                    hook["command"] = sys.executable or "python3"
    _ = hooks_path.write_text(json.dumps(hooks_document, indent=2, ensure_ascii=False) + "\n",
                              encoding="utf-8")


def install_plugins(ctx: Context, claude_dir: Path) -> None:
    """Install each plugin in claude-plugins/ as a skill dir, without touching other skills."""
    plugins_dir = ctx.repo / CLAUDE_PLUGINS_DIR
    if not plugins_dir.is_dir():
        warn(f"Source directory not found: {plugins_dir}")
        return
    for src_dir in sorted(plugins_dir.iterdir()):
        if (src_dir / ".claude-plugin" / "plugin.json").is_file():
            install_plugin(ctx, src_dir, claude_dir / "skills" / src_dir.name)


def install_plugin(ctx: Context, src_dir: Path, dst_dir: Path) -> None:
    # Rendered in a scratch copy first, so an unchanged plugin is left as it is.
    staged = ctx.work / CLAUDE_PLUGINS_DIR / src_dir.name
    if staged.exists():
        shutil.rmtree(staged)
    _ = shutil.copytree(src_dir, staged, ignore=shutil.ignore_patterns(*IGNORED_NAMES))
    try:
        render_plugin_hooks(staged / "hooks" / "hooks.json")
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        warn(f"Failed to render Claude Code hooks: {exc}")
        return
    ctx.files.replace_tree(staged, dst_dir)
    success(f"Installed Claude Code plugin: {dst_dir}")


def ensure_attribution(ctx: Context, claude_dir: Path) -> None:
    """Turn off the attribution Claude Code adds to commits and PRs; keep other settings."""
    dst = claude_dir / "settings.json"
    try:
        settings = json.loads(dst.read_text(encoding="utf-8")) if dst.exists() else {}
        if not isinstance(settings, dict):
            raise ValueError("not a JSON object")
    except (OSError, ValueError) as exc:
        warn(f"Failed to read {dst} ({type(exc).__name__}); leaving commit attribution unchanged")
        return
    current = settings.get("attribution")
    current = current if isinstance(current, dict) else {}
    if all(current.get(key) == value for key, value in CLAUDE_ATTRIBUTION.items()):
        return
    settings["attribution"] = {**current, **CLAUDE_ATTRIBUTION}
    ctx.files.write_text(dst, json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
    item("settings.json (no commit or PR attribution)")


def global_hooks_dir(ctx: Context) -> Path | None:
    """The global core.hooksPath, set to ~/.config/git/hooks when unset; None if unusable."""
    result = subprocess.run(["git", "config", "--global", "--type=path", "--get", "core.hooksPath"],
                            capture_output=True, text=True, env=dict(ctx.env))
    if result.returncode == 0 and result.stdout.strip():
        hooks_dir = Path(result.stdout.strip())
        if not hooks_dir.is_absolute():
            warn(f"core.hooksPath is relative ({result.stdout.strip()}); "
                 "each repo resolves it itself, so the commit-msg hook is not installed")
            return None
        return hooks_dir
    hooks_dir = ctx.home / ".config" / "git" / "hooks"
    _ = subprocess.run(["git", "config", "--global", "core.hooksPath", str(hooks_dir)],
                       check=True, capture_output=True, text=True, env=dict(ctx.env))
    item(f"git core.hooksPath set to {hooks_dir}")
    warn("         Hooks in each repo's .git/hooks no longer run; with git-lfs, "
         "run `git lfs install` to put its hooks there too")
    return hooks_dir


def ensure_commit_msg_hook(ctx: Context) -> None:
    """Install the commit-msg hook that drops Claude attribution lines from every commit.

    Git has no global hooks dir unless core.hooksPath is set, so it is set to
    ~/.config/git/hooks when missing; an existing value is kept and used.
    """
    src = ctx.repo / COMMIT_MSG_HOOK
    if not src.is_file():
        warn(f"Source file not found: {src}")
        return
    if shutil.which("python3") is None:
        # The hook runs through `#!/usr/bin/env python3`; without it every commit would fail.
        warn("python3 not found on PATH; commit-msg hook not installed")
        return
    try:
        hooks_dir = global_hooks_dir(ctx)
    except (OSError, subprocess.CalledProcessError) as exc:
        warn(f"git config failed ({type(exc).__name__}); commit-msg hook not installed")
        return
    if hooks_dir is None:
        return
    dst = hooks_dir / "commit-msg"
    if ctx.files.copy(src, dst):
        item(f"{dst} (drops Claude attribution lines)")
    dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class Claude(Agent):
    key = "claude"
    files = CLAUDE_FILES

    @classmethod
    def config_dir(cls, env: Mapping[str, str], home: Path) -> Path:
        configured = env.get("CLAUDE_CONFIG_DIR", "").strip()
        if configured:
            return Path(configured).expanduser()
        return home / ".claude"

    def title(self, ctx: Context) -> str:
        return f"Installing Claude Code assets to: {self.target_dir(ctx)}"

    def configure(self, ctx: Context, target: Path) -> None:
        install_plugins(ctx, target)
        ensure_attribution(ctx, target)
        ensure_commit_msg_hook(ctx)
