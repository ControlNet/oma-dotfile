"""What one install run knows: options, the repo, the environment and where each agent lives."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from functools import cached_property
from pathlib import Path

from omadotfile.constants import DEFAULT_REPO_NAME, DEFAULT_REPO_OWNER, DEFAULT_REPO_REV
from omadotfile.core.files import Files
from omadotfile.core.proc import Runner


def expand_home(path: str, home: Path) -> Path:
    """A configured path with `~` meaning the run's home; Path.expanduser would read $HOME instead.

    `~user` forms still go to expanduser, which looks the user up in the password database.
    """
    if path == "~":
        return home
    if path.startswith(("~/", "~\\")):
        return home / path[2:]
    return Path(path).expanduser() if path.startswith("~") else Path(path)


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


@dataclass(frozen=True)
class Options:
    oauth: bool = False  # --oauth: route models through each agent's own OpenAI login
    install_all: bool = False  # --all or INSTALL_ALL=1: install without detecting agents
    backup: bool = True  # NO_BACKUP=1 turns backups of changed config files off
    max_backups: int = 1  # MAX_BACKUPS: backups kept per file

    @classmethod
    def from_env(cls, env: Mapping[str, str], *, oauth: bool = False,
                 install_all: bool = False) -> "Options":
        return cls(
            oauth=oauth,
            install_all=install_all or env.get("INSTALL_ALL", "0") == "1",
            backup=env.get("NO_BACKUP", "0") != "1",
            max_backups=max(1, int(env.get("MAX_BACKUPS", "1"))),
        )


@dataclass(frozen=True)
class RepoRef:
    """The GitHub repo this checkout comes from."""

    owner: str = DEFAULT_REPO_OWNER
    name: str = DEFAULT_REPO_NAME
    rev: str = DEFAULT_REPO_REV

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "RepoRef":
        return cls(env.get("REPO_OWNER", DEFAULT_REPO_OWNER), env.get("REPO_NAME", DEFAULT_REPO_NAME),
                   env.get("REPO_REV", DEFAULT_REPO_REV))

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.name}"

    @property
    def skills_source(self) -> str:
        """How the skills CLI names this repo at this revision."""
        return f"{self.slug}#{self.rev}"


@dataclass(frozen=True)
class Context:
    repo: Path  # the checkout installed from
    work: Path  # scratch dir for downloads, removed after the run
    home: Path
    python: str  # the interpreter that runs installed hooks and the Codex notifier
    options: Options = Options()
    env: Mapping[str, str] = field(default_factory=dict)  # snapshot of os.environ
    stamp: str = field(default_factory=timestamp)  # suffix of this run's backups
    source: RepoRef = RepoRef()
    found: frozenset[str] = frozenset()  # keys of the agents to install for
    dirs: Mapping[str, Path] = field(default_factory=dict)  # config dir per agent key

    @cached_property
    def files(self) -> Files:
        return Files(self.stamp, backup=self.options.backup, keep=self.options.max_backups)

    @cached_property
    def runner(self) -> Runner:
        return Runner(self.env, self.home)

    @property
    def shared_skills_dir(self) -> Path:
        """Where the skills CLI's `universal` agent puts global skills."""
        return self.home / ".agents" / "skills"
