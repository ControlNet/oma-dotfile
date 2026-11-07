"""Turn expected errors into a [WARN] line at the edge of a function.

Pure helpers raise (ValueError for bad content, OSError from the file system). The function
that does one install action is decorated with `warns_on`, which catches the errors named
for it, prints the warning and returns None, so the run goes on. Any other exception still
aborts the run with a traceback.
"""

from collections.abc import Callable
from functools import wraps
import inspect
from string import Formatter
from typing import ParamSpec, TypeVar

from omadotfile.console import warn

P = ParamSpec("P")
R = TypeVar("R")

# Fields every message can use besides the decorated function's own parameters.
ERROR_FIELDS = frozenset({"error", "reason"})  # the exception's type name, its message


def message_fields(message: str) -> set[str]:
    """The top-level names a str.format template refers to: `{dst.name}` -> `dst`."""
    return {field.split(".")[0].split("[")[0]
            for _, field, _, _ in Formatter().parse(message) if field}


def warns_on(*errors: type[Exception], message: str) -> Callable[[Callable[P, R]], Callable[P, R | None]]:
    """Catch `errors` raised by the decorated function, warn with `message`, return None.

    `message` is a str.format template over the function's parameters plus `{error}`
    (the exception's type name) and `{reason}` (its message). A field that is neither is
    a TypeError when the function is defined, not when the warning would be printed.

        @warns_on(OSError, ValueError, message="Failed to read {dst} ({error}); leaving it unchanged")
        def update_settings(ctx: Context, dst: Path) -> bool: ...
    """

    def decorate(function: Callable[P, R]) -> Callable[P, R | None]:
        signature = inspect.signature(function)
        unknown = message_fields(message) - set(signature.parameters) - ERROR_FIELDS
        if unknown:
            raise TypeError(f"{function.__qualname__}: message names unknown fields {sorted(unknown)}")

        @wraps(function)
        def guarded(*args: P.args, **kwargs: P.kwargs) -> R | None:
            try:
                return function(*args, **kwargs)
            except errors as exc:
                arguments = signature.bind(*args, **kwargs).arguments
                warn(message.format(**arguments, error=type(exc).__name__, reason=exc))
                return None

        return guarded

    return decorate
