"""Dependency injection from the Context: by type first, by explicit provider when a type is ambiguous.

`@inject` fills a function's leading positional-only parameters from the Context by their
type, so the function names the services it really uses and callers still pass the Context:

    @inject
    def update_settings(files: Files, /, dst: Path) -> bool: ...

    update_settings(ctx, dst)

Only the service types in PROVIDERS are injected that way: each has exactly one instance in
a run. A type the Context holds several of (`repo`, `home` and `work` are all `Path`; `env` is
a `Mapping`, `python` a `str`) is ambiguous, so pyright reports "no overloads match" for it under `@inject`; such a
function names its providers instead:

    @uses(home_of, repo_of)
    def paths(home: Path, repo: Path, /, name: str) -> ...: ...

Rules both decorators keep, so the runtime injects exactly what pyright sees:
- injected parameters lead and are positional-only (before `/`);
- at most MAX_INJECTED of them (one overload per count);
- one decorator per function: the wired function takes the Context first, and Context is
  not injectable, so stacking a second one fails when decorating instead of misbinding.
"""

from collections.abc import Callable, Mapping
from functools import wraps
import inspect
from pathlib import Path
from typing import Concatenate, ParamSpec, TypeVar, overload

from omadotfile.context import Context, Options, RepoRef
from omadotfile.core.files import Files
from omadotfile.core.proc import Runner

P = ParamSpec("P")
R = TypeVar("R")
D1 = TypeVar("D1")
D2 = TypeVar("D2")
D3 = TypeVar("D3")

MAX_INJECTED = 3


def files_of(ctx: Context) -> Files:
    return ctx.files


def runner_of(ctx: Context) -> Runner:
    return ctx.runner


def options_of(ctx: Context) -> Options:
    return ctx.options


def source_of(ctx: Context) -> RepoRef:
    return ctx.source


def repo_of(ctx: Context) -> Path:
    return ctx.repo


def home_of(ctx: Context) -> Path:
    return ctx.home


def work_of(ctx: Context) -> Path:
    return ctx.work


def env_of(ctx: Context) -> Mapping[str, str]:
    return ctx.env


def python_of(ctx: Context) -> str:
    return ctx.python


# The types @inject resolves, and how. Static: nothing registers into it at import time.
PROVIDERS: dict[type, Callable[[Context], object]] = {
    Files: files_of,
    Runner: runner_of,
    Options: options_of,
    RepoRef: source_of,
}
# pyright needs the constraints spelled out; a test checks they match PROVIDERS.
Dep1 = TypeVar("Dep1", Files, Runner, Options, RepoRef)
Dep2 = TypeVar("Dep2", Files, Runner, Options, RepoRef)
Dep3 = TypeVar("Dep3", Files, Runner, Options, RepoRef)


def wire(function: Callable[..., R], providers: list[Callable[[Context], object]]) -> Callable[..., R]:
    """`function` with its first len(providers) arguments computed from the Context."""
    signature = inspect.signature(function, eval_str=True)
    rest = list(signature.parameters.values())[len(providers):]
    context = inspect.Parameter("ctx", inspect.Parameter.POSITIONAL_ONLY, annotation=Context)

    @wraps(function)
    def wired(ctx: Context, /, *args: object, **kwargs: object) -> R:
        return function(*(provide(ctx) for provide in providers), *args, **kwargs)

    # The signature callers see; also what makes a second @inject on top fail.
    wired.__signature__ = signature.replace(parameters=[context, *rest])  # type: ignore[attr-defined]
    return wired


def leading_parameters(function: Callable[..., object], count: int) -> list[inspect.Parameter]:
    """The first `count` parameters; TypeError unless all are positional-only."""
    parameters = list(inspect.signature(function, eval_str=True).parameters.values())[:count]
    loose = [p.name for p in parameters if p.kind is not inspect.Parameter.POSITIONAL_ONLY]
    if len(parameters) < count or loose:
        raise TypeError(f"{function.__qualname__}: injected parameters must lead and be positional-only "
                        f"(put / after them); not: {loose or 'enough parameters'}")
    return parameters


@overload
def inject(function: Callable[Concatenate[Dep1, Dep2, Dep3, P], R]) -> Callable[Concatenate[Context, P], R]: ...
@overload
def inject(function: Callable[Concatenate[Dep1, Dep2, P], R]) -> Callable[Concatenate[Context, P], R]: ...
@overload
def inject(function: Callable[Concatenate[Dep1, P], R]) -> Callable[Concatenate[Context, P], R]: ...
def inject(function: Callable[..., R]) -> Callable[..., R]:
    """Inject the leading parameters whose types are in PROVIDERS (see the module doc)."""
    leading = list(inspect.signature(function, eval_str=True).parameters.values())[:MAX_INJECTED]
    count = next((i for i, p in enumerate(leading) if p.annotation not in PROVIDERS), len(leading))
    if count == 0:
        raise TypeError(f"{function.__qualname__}: its first parameter is not an injectable type "
                        f"({', '.join(t.__name__ for t in PROVIDERS)}); name its providers with @uses")
    parameters = leading_parameters(function, count)
    return wire(function, [PROVIDERS[p.annotation] for p in parameters])


@overload
def uses(p1: Callable[[Context], D1], /) -> Callable[[Callable[Concatenate[D1, P], R]],
                                                     Callable[Concatenate[Context, P], R]]: ...
@overload
def uses(p1: Callable[[Context], D1], p2: Callable[[Context], D2], /) -> Callable[
    [Callable[Concatenate[D1, D2, P], R]], Callable[Concatenate[Context, P], R]]: ...
@overload
def uses(p1: Callable[[Context], D1], p2: Callable[[Context], D2], p3: Callable[[Context], D3], /) -> Callable[
    [Callable[Concatenate[D1, D2, D3, P], R]], Callable[Concatenate[Context, P], R]]: ...
def uses(*providers: Callable[[Context], object]) -> Callable[[Callable[..., R]], Callable[..., R]]:
    """Inject the leading parameters from these providers, in order (see the module doc)."""

    def decorate(function: Callable[..., R]) -> Callable[..., R]:
        _ = leading_parameters(function, len(providers))
        return wire(function, list(providers))

    return decorate
