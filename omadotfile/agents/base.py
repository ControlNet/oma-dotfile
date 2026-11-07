"""Component: an install step that installs files. Agent: a component for one detected agent.

`run` is a template method: it creates the target dir, installs the component's `files`
(see constants.FileSpec), then calls `configure` for whatever else the component does.
An Agent subclass is declared with `@agent(key, label=..., executable=...)`, which records
those on the class and registers it in AGENT_CLASSES; cli.AGENTS puts them in order.
"""

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import ClassVar, TypeVar

from omadotfile.console import item
from omadotfile.constants import FileSpec
from omadotfile.context import Context
from omadotfile.core.proc import find_executable


def file_label(spec: FileSpec) -> str:
    if Path(spec.src).name == Path(spec.dst).name:
        return spec.src
    return f"{spec.src} -> {spec.dst}"


class Component:
    """A step that installs `files` under target_dir, then runs `configure` (see omadotfile.step.Step)."""

    files: ClassVar[tuple[FileSpec, ...]] = ()
    creates_dir: ClassVar[bool] = True  # whether run() creates target_dir before anything else

    def title(self, ctx: Context) -> str:
        raise NotImplementedError

    def enabled(self, ctx: Context) -> bool:
        raise NotImplementedError

    def skip_reason(self, ctx: Context) -> str:
        raise NotImplementedError

    def target_dir(self, ctx: Context) -> Path:
        """The dir `files` are installed under."""
        raise NotImplementedError

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
    """One agent; its subclasses are declared with @agent, which sets these three."""

    key: ClassVar[str]  # "codex": the key of cli.AGENTS, ctx.found and ctx.dirs
    label: ClassVar[str]  # "Codex": the name in reports
    executable: ClassVar[str | None]  # the CLI whose presence detects the agent, if it has one

    @staticmethod
    def config_dir(env: Mapping[str, str], home: Path) -> Path:
        raise NotImplementedError

    def detect(self, env: Mapping[str, str], home: Path) -> bool:
        return find_executable(self.executable, home) is not None

    def enabled(self, ctx: Context) -> bool:
        return self.key in ctx.found

    def skip_reason(self, ctx: Context) -> str:
        return f"{self.executable} not found"

    def target_dir(self, ctx: Context) -> Path:
        return ctx.dirs[self.key]


AgentClass = TypeVar("AgentClass", bound=type[Agent])

# Every @agent class by key, in import order; cli.AGENTS gives the report order.
AGENT_CLASSES: dict[str, type[Agent]] = {}


def agent(key: str, *, label: str, executable: str | None) -> Callable[[AgentClass], AgentClass]:
    """Declare an Agent subclass: record key, label and executable on it and register it.

        @agent("codex", label="Codex", executable="codex")
        class Codex(Agent): ...
    """

    def register(cls: AgentClass) -> AgentClass:
        if key in AGENT_CLASSES:
            raise ValueError(f"agent {key!r} is registered twice: by {AGENT_CLASSES[key].__qualname__} "
                             f"and {cls.__qualname__}")
        cls.key, cls.label, cls.executable = key, label, executable
        AGENT_CLASSES[key] = cls
        return cls

    return register
