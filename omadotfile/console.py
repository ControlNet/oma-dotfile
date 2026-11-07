"""Console output: the banner, colored message prefixes and step headings."""

from collections.abc import Callable
import sys

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


def info(msg: str) -> None:
    """Print info message with cyan color."""
    print(f"{CYAN}{BOLD}[INFO]{RESET}    {msg}")


def success(msg: str) -> None:
    """Print success message with green color."""
    print(f"{GREEN}{BOLD}[SUCCESS]{RESET} {msg}")


def warn(msg: str) -> None:
    """Print warning message with yellow color."""
    # Flush first: stdout is block-buffered when piped, stderr is not, so without
    # this a warning overtakes the line it belongs to.
    sys.stdout.flush()
    print(f"{YELLOW}{BOLD}[WARN]{RESET}    {msg}", file=sys.stderr, flush=True)


def error(msg: str) -> None:
    """Print error message with red color and exit."""
    sys.stdout.flush()
    print(f"{RED}{BOLD}[ERROR]{RESET}   {msg}", file=sys.stderr, flush=True)


def step(label: str, message: str, enabled: bool, reason: str) -> bool:
    """Announce a step and report why it is skipped; return whether to run it."""
    info(f"[{label}] {message}")
    if not enabled:
        warn(f"         skipped: {reason}")
    return enabled


def item(text: str) -> None:
    """One line under a step, naming a file or setting it handles."""
    print(f"         - {text}")
