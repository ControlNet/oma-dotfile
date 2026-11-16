"""Antigravity CLI (agy): one plugin with the shared rules and a Gotify Stop hook.

agy loads every plugin under ~/.gemini/config/plugins/, and a plugin brings rules
(rules/AGENTS.md) and hooks (hooks.json at its root). The installer owns that one dir and
replaces it whole, so agy's own hooks.json, which other tools write to, and config.json,
where `agy plugin disable` is recorded, are never touched. Skills are not in the plugin:
skills.json points agy at ~/.agents/skills (features/skills.py).
"""

from collections.abc import Mapping
import os
from pathlib import Path
import shutil

from omadotfile.agents.base import Agent
from omadotfile.agents.claude import sh_quoted
from omadotfile.console import success
from omadotfile.constants import AGY_NOTIFY_SCRIPT, AGY_NOTIFY_WRAPPER, AGY_PLUGIN_DIR, AGY_PLUGIN_RULES, SHARED_RULES
from omadotfile.context import Context
from omadotfile.core.codec import JSON, JsonObject
from omadotfile.core.errors import warns_on
from omadotfile.core.files import IGNORED_NAMES
from omadotfile.inject import python_of, repo_of, uses, work_of

WINDOWS = os.name == "nt"


def oem_encoding() -> str:
    """The code page cmd reads a batch file in."""
    import ctypes
    return f"cp{ctypes.windll.kernel32.GetOEMCP()}"  # pyright: ignore[reportAttributeAccessIssue]


def hook_command(python: str) -> str:
    """The Stop hook's command line. agy runs it with `sh -c`, or `cmd /c` on Windows, in the
    plugin dir.

    On Windows it is the wrapper's relative path alone: no quote or space, so it stays one
    word however agy quotes it for cmd, whose quote handling differs from every other shell.
    """
    if WINDOWS:
        return AGY_NOTIFY_WRAPPER.replace("/", "\\")
    return f"{sh_quoted(python)} {AGY_NOTIFY_SCRIPT}"


def cmd_wrapper(python: str) -> str:
    """The Windows hook: the notifier run by this Python, its path quoted where cmd's rules
    are plain. A `%` would start a variable."""
    script = Path(AGY_NOTIFY_SCRIPT).name
    return ("@echo off\r\n"
            f"rem Installed by oma-dotfile: runs {script} with the Python that installed it.\r\n"
            f'"{python.replace("%", "%%")}" "%~dp0{script}"\r\n')


def with_command(document: JsonObject, command: str) -> JsonObject:
    """agy hooks.json with every command handler run by `command`; KeyError/TypeError if malformed.

    Events hold handlers directly, or groups of them under "hooks" for tool events.
    """
    def handler(entry: JsonObject) -> JsonObject:
        if "hooks" in entry:
            return {**entry, "hooks": [handler(inner) for inner in entry["hooks"]]}
        return {**entry, "command": command} if entry.get("type", "command") == "command" else entry

    return {name: {event: [handler(entry) for entry in entries] if isinstance(entries, list) else entries
                   for event, entries in spec.items()}
            for name, spec in document.items()}


@warns_on(UnicodeEncodeError,
          message="{python} cannot be written in code page {encoding} ({reason}); "
                  "the Antigravity CLI's Gotify hook is not installed")
def write_cmd_wrapper(staged: Path, python: str, encoding: str) -> bool:
    _ = (staged / AGY_NOTIFY_WRAPPER).write_bytes(cmd_wrapper(python).encode(encoding))
    return True


@uses(repo_of, work_of, python_of)
@warns_on(OSError, ValueError, KeyError, TypeError, message="Failed to stage the Antigravity CLI plugin: {reason}")
def stage_plugin(repo: Path, work: Path, python: str, /) -> Path:
    """A scratch copy of the plugin with the rules added and its hook rendered, so an
    unchanged one is left as it is."""
    staged = work / "agy-plugins" / Path(AGY_PLUGIN_DIR).name
    if staged.exists():
        shutil.rmtree(staged)
    _ = shutil.copytree(repo / AGY_PLUGIN_DIR, staged, ignore=shutil.ignore_patterns(*IGNORED_NAMES))
    (staged / AGY_PLUGIN_RULES).parent.mkdir(parents=True, exist_ok=True)
    _ = shutil.copyfile(repo / SHARED_RULES, staged / AGY_PLUGIN_RULES)
    hooks = staged / "hooks.json"
    if WINDOWS and not write_cmd_wrapper(staged, python, oem_encoding()):
        hooks.unlink()
        return staged
    document = with_command(JSON.load(hooks.read_text(encoding="utf-8")), hook_command(python))
    _ = hooks.write_text(JSON.dump(document), encoding="utf-8", newline="\n")
    return staged


class Antigravity(Agent, key="agy", label="Antigravity CLI", executable="agy"):
    creates_dir = False  # replace_tree makes the plugin dir

    @staticmethod
    def config_dir(env: Mapping[str, str], home: Path, platform: str) -> Path:
        return home / ".gemini" / "config"

    def target_dir(self, ctx: Context) -> Path:
        return ctx.dirs[self.key] / "plugins" / Path(AGY_PLUGIN_DIR).name

    def title(self, ctx: Context) -> str:
        return f"Installing the Antigravity CLI plugin to: {self.target_dir(ctx)}"

    def run(self, ctx: Context) -> None:
        target = self.target_dir(ctx)
        staged = stage_plugin(ctx)
        if staged is not None and ctx.files.replace_tree(staged, target):
            hook = ", Gotify Stop hook" if (staged / "hooks.json").is_file() else ""
            success(f"Installed Antigravity CLI plugin: {target} ({AGY_PLUGIN_RULES}{hook})")
