"""Mark one-off cleanups so they are listed in one place and deleted on time.

A migration cleans up after an older version of this repo or of an agent: a renamed config
file, a copy that now lives elsewhere. It runs on every install until its code is deleted,
so a machine that has not pulled for months still gets cleaned up. tests/test_migrations.py
fails once a migration's `remove_by` month has begun; then delete it, or move the date if some
machine may still need it.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

F = TypeVar("F", bound=Callable[..., object])


@dataclass(frozen=True)
class Migration:
    name: str  # module.function
    since: str  # YYYY-MM it was added
    reason: str  # what it cleans up after
    remove_by: str  # YYYY-MM from which tests fail until it is deleted


MIGRATIONS: list[Migration] = []


def migration(*, since: str, reason: str, remove_by: str) -> Callable[[F], F]:
    """Register the decorated function as a migration; the function itself is unchanged."""

    def register(function: F) -> F:
        MIGRATIONS.append(Migration(f"{function.__module__}.{function.__qualname__}",
                                    since, reason, remove_by))
        return function

    return register
