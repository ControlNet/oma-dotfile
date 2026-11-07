"""Find agent CLIs and run them."""

from collections.abc import Mapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from omadotfile.console import warn

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


def find_executable(name: str | None, home: Path) -> Path | None:
    """Resolve a CLI from PATH, then from known per-user install locations under home."""
    if not name:
        return None
    found = shutil.which(name) or shutil.which(name, path=extra_bin_search_path(home))
    return Path(found) if found else None


@dataclass(frozen=True)
class Runner:
    """Runs CLIs with the run's environment; `extra_env` pins an agent's config dir."""

    env: Mapping[str, str]
    home: Path

    def which(self, name: str | None) -> Path | None:
        return find_executable(name, self.home)

    def run(self, command: list[str],
            extra_env: Mapping[str, str] | None = None) -> subprocess.CompletedProcess[str] | None:
        """Run command; None (with a warning) if it cannot start or exits non-zero."""
        env = {**self.env, **(extra_env or {})}
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
            warn(f"Failed to run {' '.join(command)}: {exc}")
            return None
        if result.returncode != 0:
            # Command output may contain tokens or local paths, so it is not printed.
            warn(f"{' '.join(command)} failed with exit code {result.returncode}")
            return None
        return result

    def ok(self, command: list[str], extra_env: Mapping[str, str] | None = None) -> bool:
        """Run a command whose success is reported only by its exit code."""
        return self.run(command, extra_env) is not None

    def json(self, command: list[str], extra_env: Mapping[str, str] | None = None) -> object | None:
        """Run a command that prints JSON and return the parsed document."""
        result = self.run(command, extra_env)
        if result is None:
            return None
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            warn(f"Failed to parse JSON output of {' '.join(command)}")
            return None
