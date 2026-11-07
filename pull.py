#!/usr/bin/env python3
"""Install the oma-dotfile agent configs.

    curl -fsSL https://raw.githubusercontent.com/ControlNet/oma-dotfile/master/pull.py | python3

Clones REPO_OWNER/REPO_NAME at REPO_REV (default ControlNet/oma-dotfile, master) and runs the
omadotfile package from that clone. `--repo PATH` uses a local checkout instead; every other
argument (`--oauth`, `--all`, ...) is passed on to omadotfile.

Run through `curl | python3`, this file has no path of its own, so it cannot find a checkout
next to it. It keeps to syntax old Pythons can parse, so that they get a clear message.
"""

import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

MIN_PYTHON = (3, 10)


def fail(message):
    sys.stdout.flush()
    print("[ERROR]   " + message, file=sys.stderr, flush=True)
    sys.exit(1)


def split_repo_arg(argv):
    """Return (the --repo path or None, the other arguments)."""
    repo, rest = None, []
    args = iter(argv)
    for arg in args:
        if arg == "--repo":
            repo = next(args, None)
            if not repo:
                fail("--repo needs a path")
        elif arg.startswith("--repo="):
            repo = arg[len("--repo="):]
        else:
            rest.append(arg)
    return repo, rest


def run(repo_dir, argv):
    """Run omadotfile from repo_dir, ahead of any other omadotfile on sys.path."""
    if not (repo_dir / "omadotfile" / "__init__.py").is_file():
        fail("{} has no omadotfile package; it is older than this pull.py".format(repo_dir))
    sys.path.insert(0, str(repo_dir))
    from omadotfile.cli import main
    main(argv, repo=repo_dir)


def main(argv):
    if sys.version_info < MIN_PYTHON:
        fail("oma-dotfile needs Python {}.{} or newer; this is {}".format(
            MIN_PYTHON[0], MIN_PYTHON[1], platform.python_version()))
    repo, argv = split_repo_arg(argv)
    if repo:
        run(Path(repo).expanduser().resolve(), argv)
        return
    owner = os.environ.get("REPO_OWNER", "ControlNet")
    name = os.environ.get("REPO_NAME", "oma-dotfile")
    rev = os.environ.get("REPO_REV", "master")
    with tempfile.TemporaryDirectory() as tmp:
        repo_dir = Path(tmp) / name
        print("Cloning {}/{} ({})...".format(owner, name, rev), flush=True)
        result = subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", rev,
             "https://github.com/{}/{}.git".format(owner, name), str(repo_dir)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        if result.returncode != 0:
            print(result.stderr, file=sys.stderr)
            fail("Failed to clone {}/{} ({})".format(owner, name, rev))
        run(repo_dir, argv)


if __name__ == "__main__":
    main(sys.argv[1:])
