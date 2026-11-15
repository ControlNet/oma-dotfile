"""Claude Code: the shared rules, plugins, no commit attribution, and the commit-msg hook."""

from collections.abc import Mapping
from pathlib import Path
import shutil
import stat

from omadotfile.agents.base import Agent
from omadotfile.console import item, success, warn
from omadotfile.constants import CLAUDE_ATTRIBUTION, CLAUDE_FILES, CLAUDE_PLUGINS_DIR, COMMIT_MSG_HOOK
from omadotfile.context import Context, expand_home
from omadotfile.core.codec import JSON, JsonObject
from omadotfile.core.errors import warns_on
from omadotfile.core.files import IGNORED_NAMES, Files
from omadotfile.core.proc import CommandFailed, Runner
from omadotfile.inject import home_of, inject, python_of, runner_of, uses, work_of


def with_hook_command(document: JsonObject, command: str) -> JsonObject:
    """hooks.json with every command hook run by `command`; KeyError/TypeError if malformed."""
    return {**document, "hooks": {
        event: [{**entry, "hooks": [{**hook, "command": command} if hook.get("type") == "command" else hook
                                    for hook in entry["hooks"]]}
                for entry in entries]
        for event, entries in document["hooks"].items()
    }}


def install_plugins(ctx: Context, claude_dir: Path) -> None:
    """Install each plugin in config/claude/plugins/ as a skill dir, without touching other skills."""
    plugins_dir = ctx.repo / CLAUDE_PLUGINS_DIR
    if not plugins_dir.is_dir():
        warn(f"Source directory not found: {plugins_dir}")
        return
    for src_dir in sorted(plugins_dir.iterdir()):
        if (src_dir / ".claude-plugin" / "plugin.json").is_file():
            install_plugin(ctx, src_dir, claude_dir / "skills" / src_dir.name)


def install_plugin(ctx: Context, src_dir: Path, dst_dir: Path) -> None:
    staged = stage_plugin(ctx, src_dir)
    if staged is None:
        return
    if ctx.files.replace_tree(staged, dst_dir):
        success(f"Installed Claude Code plugin: {dst_dir}")


@uses(work_of, python_of)
@warns_on(OSError, ValueError, KeyError, TypeError, message="Failed to render Claude Code hooks: {reason}")
def stage_plugin(work: Path, python: str, /, src_dir: Path) -> Path:
    """A scratch copy of the plugin with its hooks rendered, so an unchanged one is left as it is."""
    staged = work / "claude-plugins" / src_dir.name
    if staged.exists():
        shutil.rmtree(staged)
    _ = shutil.copytree(src_dir, staged, ignore=shutil.ignore_patterns(*IGNORED_NAMES))
    hooks = staged / "hooks" / "hooks.json"
    # The plugin's scripts import from this Python's standard library only; run them with it.
    document = with_hook_command(JSON.load(hooks.read_text(encoding="utf-8")), python)
    _ = hooks.write_text(JSON.dump(document), encoding="utf-8", newline="\n")
    return staged


def without_attribution(settings: JsonObject) -> JsonObject:
    """Settings with the commit and PR attribution turned off; other keys are kept."""
    current = settings.get("attribution")
    current = current if isinstance(current, dict) else {}
    if all(current.get(key) == value for key, value in CLAUDE_ATTRIBUTION.items()):
        return settings
    return {**settings, "attribution": {**current, **CLAUDE_ATTRIBUTION}}


def ensure_attribution(ctx: Context, claude_dir: Path) -> None:
    """Turn off the attribution Claude Code adds to commits and PRs; keep other settings."""
    if update_settings(ctx, claude_dir / "settings.json"):
        item("settings.json (no commit or PR attribution)")


@inject
@warns_on(OSError, ValueError, message="Failed to read {dst} ({error}); leaving commit attribution unchanged")
def update_settings(files: Files, /, dst: Path) -> bool:
    return files.update(dst, JSON, without_attribution)


@uses(runner_of, home_of)
@warns_on(CommandFailed, message="{reason}; commit-msg hook not installed")
def global_hooks_dir(runner: Runner, home: Path, /) -> Path | None:
    """The global core.hooksPath, set to ~/.config/git/hooks when unset; None if unusable."""
    # Unchecked: git exits 1 when the key is unset.
    result = runner.run(["git", "config", "--global", "--type=path", "--get", "core.hooksPath"], check=False)
    if result.returncode == 0 and result.stdout.strip():
        hooks_dir = Path(result.stdout.strip())
        if not hooks_dir.is_absolute():
            warn(f"core.hooksPath is relative ({result.stdout.strip()}); "
                 "each repo resolves it itself, so the commit-msg hook is not installed")
            return None
        return hooks_dir
    hooks_dir = home / ".config" / "git" / "hooks"
    _ = runner.run(["git", "config", "--global", "core.hooksPath", str(hooks_dir)])
    item(f"git core.hooksPath set to {hooks_dir}")
    warn("         Hooks in each repo's .git/hooks no longer run; with git-lfs, "
         "run `git lfs install` to put its hooks there too")
    return hooks_dir


def sh_quoted(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def commit_msg_wrapper(python: str, script: Path) -> str:
    """The commit-msg hook git runs: the script, run by this Python, never blocking a commit.

    Not `#!/usr/bin/env python3`: a GUI client, an IDE or cron may commit with no python3 on
    PATH, and on Windows python3 is often only the Store's alias, which exits non-zero; git
    refuses the commit either way. Paths are written with / for Git for Windows' sh.
    """
    return f"""#!/bin/sh
# Installed by oma-dotfile: drops Claude attribution lines with the script below, run by the
# Python that installed it. It never blocks a commit.
python={sh_quoted(Path(python).as_posix())}
script={sh_quoted(script.as_posix())}
if [ ! -f "$python" ] || [ ! -f "$script" ]; then
    echo "oma-dotfile commit-msg hook: $python or $script is missing; rerun pull.py" >&2
    exit 0
fi
"$python" "$script" "$@" || :
exit 0
"""


def ensure_commit_msg_hook(ctx: Context) -> None:
    """Install the commit-msg hook that drops Claude attribution lines from every commit.

    Git has no global hooks dir unless core.hooksPath is set, so it is set to
    ~/.config/git/hooks when missing; an existing value is kept and used. The hook is a sh
    wrapper (commit_msg_wrapper) around commit-msg.py, a name git never runs as a hook.
    """
    src = ctx.repo / COMMIT_MSG_HOOK
    if not src.is_file():
        warn(f"Source file not found: {src}")
        return
    hooks_dir = global_hooks_dir(ctx)
    if hooks_dir is None:
        return
    script = hooks_dir / src.name
    dst = hooks_dir / "commit-msg"
    if ctx.files.copy(src, script):
        item(f"{script} (drops Claude attribution lines)")
    if ctx.files.write_text(dst, commit_msg_wrapper(ctx.python, script)):
        item(f"{dst} (runs {src.name} with {ctx.python})")
    dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class Claude(Agent, key="claude", label="Claude Code", executable="claude"):
    files = CLAUDE_FILES

    @staticmethod
    def config_dir(env: Mapping[str, str], home: Path, platform: str) -> Path:
        configured = env.get("CLAUDE_CONFIG_DIR", "").strip()
        if configured:
            return expand_home(configured, home)
        return home / ".claude"

    def title(self, ctx: Context) -> str:
        return f"Installing Claude Code assets to: {self.target_dir(ctx)}"

    @staticmethod
    def configure(ctx: Context, target: Path) -> None:
        install_plugins(ctx, target)
        ensure_attribution(ctx, target)
        ensure_commit_msg_hook(ctx)
