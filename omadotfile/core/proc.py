"""Find agent CLIs and run them."""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from omadotfile.core.errors import Skip

# Interactive shells add these; `curl ... | python3 -` often does not.
EXTRA_BIN_DIRS = (".opencode/bin", ".bun/bin", ".local/bin", ".npm-global/bin")
COMMAND_TIMEOUT = 300


def extra_bin_search_path(home: Path) -> str:
    """Build a PATH of per-user bin directories a non-interactive shell may omit."""
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


def on_path(name: str, env: Mapping[str, str]) -> Path | None:
    """Resolve a command from env's PATH alone, as a shell or shebang with that env would.

    An env without PATH gets os.defpath, never the process PATH (shutil.which's fallback).
    """
    found = shutil.which(name, path=env.get("PATH", os.defpath))
    return Path(found) if found else None


def find_executable(name: str | None, env: Mapping[str, str], home: Path) -> Path | None:
    """Resolve a CLI from env's PATH, then from known per-user install locations under home."""
    if not name:
        return None
    found = on_path(name, env) or shutil.which(name, path=extra_bin_search_path(home))
    return Path(found) if found else None


class CommandFailed(Skip):
    """A CLI could not start, exited non-zero, or printed JSON that does not parse.

    A Skip, so an action decorated with @skips prints the message and stops; a caller that
    can go on without the result catches it (or calls through a @skips helper).
    """


@dataclass(frozen=True)
class Runner:
    """Runs CLIs with the run's environment, plus `pin`: the env that points a CLI at an agent's dir."""

    env: Mapping[str, str]
    home: Path
    pin: Mapping[str, str] = field(default_factory=dict[str, str])

    def pinned(self, pin: Mapping[str, str]) -> "Runner":
        """This runner with `pin` added to what it already pins."""
        return replace(self, pin={**self.pin, **pin})

    def which(self, name: str | None) -> Path | None:
        """Where a CLI is: PATH, then per-user bin dirs (see find_executable)."""
        return find_executable(name, self.env, self.home)

    def on_path(self, name: str) -> Path | None:
        """Where `name` is on this run's PATH alone: what a hook or shebang will find."""
        return on_path(name, self.env)

    def run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        """Run command; CommandFailed if it cannot start or exits non-zero."""
        env = {**self.env, **self.pin}
        executable = self.which(command[0])
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
                timeout=COMMAND_TIMEOUT,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise CommandFailed(f"Failed to run {' '.join(command)}: {exc}") from exc
        if result.returncode != 0:
            # Command output may contain tokens or local paths, so it is not in the message.
            raise CommandFailed(f"{' '.join(command)} failed with exit code {result.returncode}")
        return result

    def json(self, command: list[str]) -> object:
        """Run a command that prints JSON and return the parsed document."""
        result = self.run(command)
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise CommandFailed(f"Failed to parse JSON output of {' '.join(command)}") from exc
