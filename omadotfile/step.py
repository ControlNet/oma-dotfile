"""Step: one numbered install step, and the @step decorator for steps that are functions.

`Step` is a Protocol: an agent class (agents.base.Component) and a decorated function
(FunctionStep) are both steps without sharing a base class. cli.STEPS lists them in order.
`found_any`, `found_executable` and `either` are a step's preconditions (which agents or
CLIs it is for); `requires` gates an action inside a step on the CLIs it needs.
"""

from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import Concatenate, ParamSpec, Protocol, TypeVar, runtime_checkable

from omadotfile.console import warn
from omadotfile.context import Context

P = ParamSpec("P")
R = TypeVar("R")

Predicate = Callable[[Context], bool]
Action = Callable[[Context], None]


@runtime_checkable
class Step(Protocol):
    def title(self, ctx: Context) -> str: ...

    def enabled(self, ctx: Context) -> bool: ...

    def skip_reason(self, ctx: Context) -> str: ...

    def run(self, ctx: Context) -> None: ...


@dataclass(frozen=True)
class FunctionStep:
    """A step made from a function by @step."""

    heading: str
    when: Predicate
    reason: str
    action: Action

    def title(self, ctx: Context) -> str:
        return self.heading

    def enabled(self, ctx: Context) -> bool:
        return self.when(ctx)

    def skip_reason(self, ctx: Context) -> str:
        return self.reason

    def run(self, ctx: Context) -> None:
        self.action(ctx)


def step(title: str, *, when: Predicate, skip: str) -> Callable[[Action], FunctionStep]:
    """Make the decorated function a step; it runs when `when(ctx)`, else `skip` is shown.

        @step("Installing shared skills", when=found_any("codex", "claude"), skip="no agent found")
        def install_shared_skills(ctx: Context) -> None: ...
    """

    def wrap(action: Action) -> FunctionStep:
        return FunctionStep(title, when, skip, action)

    return wrap


def found_any(*keys: str) -> Predicate:
    """A predicate that holds when any of these agents is installed for."""

    def found(ctx: Context) -> bool:
        return any(key in ctx.found for key in keys)

    return found


def found_executable(*names: str) -> Predicate:
    """A predicate that holds when every one of these CLIs is found (ctx.runner.which), in order."""

    def found(ctx: Context) -> bool:
        return all(ctx.runner.which(name) is not None for name in names)

    return found


def either(*predicates: Predicate) -> Predicate:
    """A predicate that holds when any of these does, tried in order."""

    def holds(ctx: Context) -> bool:
        return any(predicate(ctx) for predicate in predicates)

    return holds


def requires(*executables: str, skip: str | None) -> Callable[[Callable[Concatenate[Context, P], R]],
                                                      Callable[Concatenate[Context, P], R | None]]:
    """Run the decorated action only if every executable is found; else warn `skip`, return None.

    skip=None stops without a word: for an optional extra that most machines do not have.

    The action takes the Context first; executables are looked up the way the run finds
    them (ctx.runner.which), in order, stopping at the first one missing.

        @requires("npx", skip="skills skipped: npx not found (install Node.js)")
        def ensure_skills(ctx: Context, legacy_skill_dirs: list[Path]) -> None: ...
    """

    def decorate(action: Callable[Concatenate[Context, P], R]) -> Callable[Concatenate[Context, P], R | None]:
        @wraps(action)
        def checked(ctx: Context, /, *args: P.args, **kwargs: P.kwargs) -> R | None:
            if not found_executable(*executables)(ctx):
                if skip is not None:
                    warn(skip)
                return None
            return action(ctx, *args, **kwargs)

        return checked

    return decorate
