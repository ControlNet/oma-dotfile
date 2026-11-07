"""Component: an install step that installs files. Agent: a component for one detected agent.

`run` is a template method: it creates the target dir, installs the component's `files`
(see constants.FileSpec), then calls `configure` for whatever else the component does.
An Agent subclass names itself in its class statement:
`class Codex(Agent, key="codex", label="Codex", executable="codex")`. cli.AGENTS lists them.
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from pathlib import Path
from typing import ClassVar

from omadotfile.console import item
from omadotfile.constants import FileSpec
from omadotfile.context import Context
from omadotfile.core.proc import find_executable


def file_label(spec: FileSpec) -> str:
    """The repo file's name, or `name -> dst` when it is installed under another name."""
    name = Path(spec.src).name
    return name if name == Path(spec.dst).name else f"{name} -> {spec.dst}"


class Component(ABC):
    """A step that installs `files` under target_dir, then runs `configure` (see omadotfile.step.Step).

    The four abstract methods are what every component must say; a subclass that leaves one
    out cannot be instantiated (pyright reports it, Python raises TypeError).
    """

    files: ClassVar[tuple[FileSpec, ...]] = ()
    creates_dir: ClassVar[bool] = True  # whether run() creates target_dir before anything else

    @abstractmethod
    def title(self, ctx: Context) -> str:
        ...

    @abstractmethod
    def enabled(self, ctx: Context) -> bool:
        ...

    @abstractmethod
    def skip_reason(self, ctx: Context) -> str:
        ...

    @abstractmethod
    def target_dir(self, ctx: Context) -> Path:
        """The dir `files` are installed under."""
        ...

    def run(self, ctx: Context) -> None:
        target = self.target_dir(ctx)
        if self.creates_dir:
            target.mkdir(parents=True, exist_ok=True)
        for spec in self.files:
            self.install_file(ctx, spec, target)
        self.configure(ctx, target)

    def install_file(self, ctx: Context, spec: FileSpec, target: Path) -> None:
        src = ctx.repo / spec.src
        if not src.exists():
            return
        item(file_label(spec))
        dst = target / spec.dst
        if spec.merge:
            self.install_merged_file(ctx, spec, src, dst)
        elif spec.oauth and ctx.options.oauth:
            self.install_oauth_file(ctx, src, dst)
        else:
            ctx.files.copy(src, dst, backup=not spec.managed)

    @staticmethod
    def install_oauth_file(ctx: Context, src: Path, dst: Path) -> None:
        """Write the --oauth variant of a file marked `oauth` in `files`."""
        raise NotImplementedError(f"no OAuth variant of {src.name}")

    @staticmethod
    def install_merged_file(ctx: Context, spec: FileSpec, src: Path, dst: Path) -> None:
        """Merge a file marked `merge` in `files` into the one on disk."""
        raise NotImplementedError(f"cannot merge {src.name}")

    @staticmethod
    def configure(ctx: Context, target: Path) -> None:
        """Everything the component does besides installing `files`."""


class Agent(Component):
    """One agent; a subclass passes these three as keywords of its class statement."""

    key: ClassVar[str]  # "codex": the key of cli.AGENTS, ctx.found and ctx.dirs
    label: ClassVar[str]  # "Codex": the name in reports
    executable: ClassVar[str | None]  # the CLI whose presence detects the agent, if it has one

    def __init_subclass__(cls, *, key: str, label: str, executable: str | None, **kwargs: object) -> None:
        """`class Codex(Agent, key="codex", label="Codex", executable="codex")`.

        All three are required, so pyright reports a subclass that leaves one out and Python
        raises TypeError when the class is defined.
        """
        super().__init_subclass__(**kwargs)
        cls.key, cls.label, cls.executable = key, label, executable

    @staticmethod
    @abstractmethod
    def config_dir(env: Mapping[str, str], home: Path) -> Path:
        """The agent's config dir, found from the env the way the agent itself finds it."""
        ...

    def detect(self, env: Mapping[str, str], home: Path) -> bool:
        return find_executable(self.executable, home) is not None

    def enabled(self, ctx: Context) -> bool:
        return self.key in ctx.found

    def skip_reason(self, ctx: Context) -> str:
        return f"{self.executable} not found"

    def target_dir(self, ctx: Context) -> Path:
        return ctx.dirs[self.key]

