"""Step: one numbered install step, and the @step decorator for steps that are functions.

`Step` is a Protocol: an agent class (agents.base.Component) and a decorated function
(FunctionStep) are both steps without sharing a base class. cli.STEPS lists them in order.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from omadotfile.context import Context

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
