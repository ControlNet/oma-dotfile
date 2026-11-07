"""Shared test helpers: a Context over temporary directories, never the real home."""

from collections.abc import Iterable, Mapping
from contextlib import AbstractContextManager
from pathlib import Path
import sys
from typing import TypeVar
import unittest

from omadotfile.context import Context, Options, RepoRef

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    tomllib = None

ROOT = Path(__file__).resolve().parents[1]
STAMP = "20260908-120000"
T = TypeVar("T")

# Tests that parse the TOML the installer wrote need a real parser; Python 3.10 has none.
# The installer's own no-tomllib path is covered by test_pull_toml_fallback on every version.
requires_tomllib = unittest.skipIf(tomllib is None, "needs tomllib (Python 3.11+) to check the TOML")


class TestCase(unittest.TestCase):
    """unittest.TestCase, with enterContext on Python 3.10 too."""

    if sys.version_info < (3, 11):
        def enterContext(self, cm: AbstractContextManager[T]) -> T:
            result = cm.__enter__()
            self.addCleanup(cm.__exit__, None, None, None)
            return result


def make_context(home: Path, *, repo: Path = ROOT, work: Path | None = None, oauth: bool = False,
                 backup: bool = True, max_backups: int = 1, env: Mapping[str, str] | None = None,
                 found: Iterable[str] = (), dirs: Mapping[str, Path] | None = None,
                 stamp: str = STAMP, source: RepoRef = RepoRef(), platform: str = sys.platform,
                 python: str = sys.executable) -> Context:
    """A Context whose home, scratch dir and agent dirs all live under `home`.

    Agent dirs default to the ones each agent finds from `env` and `home`, as cli.main does.
    """
    from omadotfile.cli import AGENTS

    env = dict(env or {})
    if dirs is None:
        dirs = {key: agent.config_dir(env, home, platform) for key, agent in AGENTS.items()}
    return Context(
        repo=repo,
        work=work if work is not None else home / ".work",
        options=Options(oauth=oauth, backup=backup, max_backups=max_backups),
        env=env,
        home=home,
        python=python,
        stamp=stamp,
        source=source,
        found=frozenset(found),
        dirs=dict(dirs),
    )
