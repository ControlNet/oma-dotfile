"""Shared test helpers: a Context over temporary directories, never the real home."""

from collections.abc import Iterable, Mapping
from pathlib import Path

from omadotfile.context import Context, Options, RepoRef

ROOT = Path(__file__).resolve().parents[1]
STAMP = "20260908-120000"


def make_context(home: Path, *, repo: Path = ROOT, work: Path | None = None, oauth: bool = False,
                 backup: bool = True, max_backups: int = 1, env: Mapping[str, str] | None = None,
                 found: Iterable[str] = (), dirs: Mapping[str, Path] | None = None,
                 stamp: str = STAMP, source: RepoRef = RepoRef()) -> Context:
    """A Context whose home, scratch dir and agent dirs all live under `home`.

    Agent dirs default to the ones each agent finds from `env` and `home`, as cli.main does.
    """
    from omadotfile.cli import AGENTS

    env = dict(env or {})
    if dirs is None:
        dirs = {key: agent.config_dir(env, home) for key, agent in AGENTS.items()}
    return Context(
        repo=repo,
        work=work if work is not None else home / ".work",
        options=Options(oauth=oauth, backup=backup, max_backups=max_backups),
        env=env,
        home=home,
        stamp=stamp,
        source=source,
        found=frozenset(found),
        dirs=dict(dirs),
    )
