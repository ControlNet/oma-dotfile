"""Console output: the banner, colored message prefixes and step headings.

Every line goes to the Console bound for the run, by default the Terminal. `cli.main` binds
one with `use_console`, like a logging handler: code that prints, the error decorators
included, calls `info`/`warn`/... and never needs the Console passed in. A test binds a
recorder and reads the lines it kept instead of capturing stdout/stderr.
"""

from collections.abc import Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import re
import sys
from typing import Literal, Protocol, TypeVar

# Where a config transform reports what it could not do: `warn` in a run, `list.append` in a
# test. Passing it keeps the transform free of print calls of its own.
Note = Callable[[str], None]

RESET = "\033[0m"
BOLD = "\033[1m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
MAGENTA = "\033[35m"

BANNER = f"""{CYAN}{BOLD}
 ██████╗ ██████╗ ███╗   ██╗████████╗██████╗  ██████╗ ██╗     ███╗   ██╗███████╗████████╗
██╔════╝██╔═══██╗████╗  ██║╚══██╔══╝██╔══██╗██╔═══██╗██║     ████╗  ██║██╔════╝╚══██╔══╝
██║     ██║   ██║██╔██╗ ██║   ██║   ██████╔╝██║   ██║██║     ██╔██╗ ██║█████╗     ██║   
██║     ██║   ██║██║╚██╗██║   ██║   ██╔══██╗██║   ██║██║     ██║╚██╗██║██╔══╝     ██║   
╚██████╗╚██████╔╝██║ ╚████║   ██║   ██║  ██║╚██████╔╝███████╗██║ ╚████║███████╗   ██║   
 ╚═════╝ ╚═════╝ ╚═╝  ╚═══╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝╚══════╝   ╚═╝   
{RESET}
{MAGENTA}{BOLD}                         ██████╗ ███╗   ███╗ █████╗ 
                        ██╔═══██╗████╗ ████║██╔══██╗
                        ██║   ██║██╔████╔██║███████║
                        ██║   ██║██║╚██╔╝██║██╔══██║
                        ╚██████╔╝██║ ╚═╝ ██║██║  ██║
                        ╚═════╝ ╚═╝     ╚═╝╚═╝  ╚═╝
{RESET}
{CYAN}  ══════════════════════════════════════════════════════════════════════════════
{YELLOW}                ControlNet Oh-My-Agents Configuration Installer
{CYAN}  ══════════════════════════════════════════════════════════════════════════════{RESET}
"""


Level = Literal["text", "info", "success", "warn", "error", "item"]


class Console(Protocol):
    """Where output lines go; `level` says what kind of line `text` is."""

    def emit(self, level: Level, text: str, /) -> None: ...


PREFIXES: dict[Level, str] = {
    "text": "",
    "info": f"{CYAN}{BOLD}[INFO]{RESET}    ",
    "success": f"{GREEN}{BOLD}[SUCCESS]{RESET} ",
    "warn": f"{YELLOW}{BOLD}[WARN]{RESET}    ",
    "error": f"{RED}{BOLD}[ERROR]{RESET}   ",
    "item": "         - ",
}


class Terminal:
    """Colored lines on stdout, warnings and errors on stderr.

    The streams are looked up for each line, so contextlib.redirect_stdout still captures them.
    """

    def emit(self, level: Level, text: str, /) -> None:
        if level in ("warn", "error"):
            # Flush first: stdout is block-buffered when piped, stderr is not, so without
            # this a warning overtakes the line it belongs to.
            sys.stdout.flush()
            print(PREFIXES[level] + text, file=sys.stderr, flush=True)
        else:
            print(PREFIXES[level] + text)


class HomeAsTilde:
    """A Console that writes the home directory as `~` before passing each line on.

    Output gets pasted into issues and chats; this keeps the user name out of it.
    """

    def __init__(self, inner: Console, home: Path) -> None:
        self.inner = inner
        # Only the whole directory: not /home/user for /home/u, not /mnt/home/u.
        self.pattern = re.compile(rf"(?<![\w.~/\\-]){re.escape(str(home))}(?![\w.-])") if home.name else None

    def emit(self, level: Level, text: str, /) -> None:
        self.inner.emit(level, text if self.pattern is None else self.pattern.sub("~", text))


CURRENT: ContextVar[Console] = ContextVar("console", default=Terminal())
C = TypeVar("C", bound=Console)


def current_console() -> Console:
    return CURRENT.get()


@contextmanager
def use_console(console: C) -> Generator[C, None, None]:
    """Send every line printed inside the block to `console`; nested blocks win."""
    token = CURRENT.set(console)
    try:
        yield console
    finally:
        CURRENT.reset(token)


def line(text: str = "") -> None:
    """A line as it is, without a prefix (the banner, a blank line)."""
    current_console().emit("text", text)


def info(msg: str) -> None:
    current_console().emit("info", msg)


def success(msg: str) -> None:
    current_console().emit("success", msg)


def warn(msg: str) -> None:
    current_console().emit("warn", msg)


def error(msg: str) -> None:
    current_console().emit("error", msg)


def item(text: str) -> None:
    """One line under a step, naming a file or setting it handles."""
    current_console().emit("item", text)


def step(label: str, message: str, enabled: bool, reason: str) -> bool:
    """Announce a step and report why it is skipped; return whether to run it."""
    info(f"[{label}] {message}")
    if not enabled:
        warn(f"         skipped: {reason}")
    return enabled
