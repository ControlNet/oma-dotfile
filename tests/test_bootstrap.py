"""Tests for pull.py, the bootstrap that runs omadotfile.

Nothing is cloned or installed: omadotfile.cli.main is replaced by a mock.
"""

import ast
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pull_bootstrap", ROOT / "pull.py")
assert SPEC is not None and SPEC.loader is not None
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)
sys.path.insert(0, str(ROOT))
import omadotfile.cli  # noqa: E402  (the module run() imports)
from support import TestCase


def errors_of(function, *args) -> str:
    with contextlib.redirect_stderr(io.StringIO()) as err, \
            contextlib.redirect_stdout(io.StringIO()), \
            unittest.TestCase().assertRaises(SystemExit):
        function(*args)
    return err.getvalue()


class Stream(io.StringIO):
    """A captured stdout that says whether it is a terminal."""

    def __init__(self, terminal: bool):
        super().__init__()
        self.terminal = terminal

    def isatty(self) -> bool:
        return self.terminal


def visible(text: str) -> str:
    """What a terminal shows of one line written with carriage returns."""
    shown: list[str] = []
    column = 0
    for char in text:
        if char == "\r":
            column = 0
        else:
            shown[column:column + 1] = [char]
            column += 1
    return "".join(shown).strip()


class BootstrapTests(TestCase):
    def test_repo_argument_is_taken_out_and_the_rest_passed_on(self):
        self.assertEqual(bootstrap.split_repo_arg(["--oauth", "--repo", "/x", "--all"]),
                         ("/x", ["--oauth", "--all"]))
        self.assertEqual(bootstrap.split_repo_arg(["--repo=/y"]), ("/y", []))
        self.assertEqual(bootstrap.split_repo_arg(["--oauth"]), (None, ["--oauth"]))
        self.assertIn("--repo needs a path", errors_of(bootstrap.split_repo_arg, ["--repo"]))

    def test_local_checkout_runs_its_own_package(self):
        with patch.object(omadotfile.cli, "main") as main:
            bootstrap.main(["--repo", str(ROOT), "--oauth"])
        main.assert_called_once_with(["--oauth"], repo=ROOT)

    def test_checkout_without_the_package_is_refused_in_one_line(self):
        with tempfile.TemporaryDirectory() as directory:
            message = errors_of(bootstrap.run, Path(directory), [])
        self.assertIn("has no omadotfile package", message)
        self.assertNotIn("Traceback", message)

    def test_a_checkout_under_home_is_named_with_a_tilde(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(bootstrap.Path, "home", return_value=Path(directory)):
            message = errors_of(bootstrap.run, Path(directory) / "src" / "dotfile", [])
        self.assertIn("~/src/dotfile has no omadotfile package", message)
        self.assertNotIn(directory, message)

    def clone(self, terminal: bool, returncode: int = 0) -> tuple[str, str]:
        """Run the clone path with git and omadotfile mocked; what it wrote to stdout and stderr."""
        out, err = Stream(terminal), io.StringIO()
        done = subprocess.CompletedProcess(["git"], returncode, stdout="", stderr="fatal: no such ref\n")
        with patch.dict(os.environ, {"REPO_OWNER": "o", "REPO_NAME": "n", "REPO_REV": "r"}), \
                patch.object(bootstrap.subprocess, "run", return_value=done), \
                patch.object(bootstrap, "run") as run, \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                contextlib.suppress(SystemExit):
            bootstrap.main(["--oauth"])
        self.assertEqual(run.called, returncode == 0)
        return out.getvalue(), err.getvalue()

    def test_clone_status_is_shown_on_a_terminal_and_cleared_before_the_banner(self):
        out, _ = self.clone(terminal=True)
        self.assertTrue(out.startswith("Cloning o/n (r)..."), out)
        self.assertEqual(visible(out), "")
        self.assertNotIn("\n", out)

    def test_clone_status_is_not_written_off_a_terminal(self):
        self.assertEqual(self.clone(terminal=False)[0], "")

    def test_failed_clone_clears_the_status_and_reports_why(self):
        out, err = self.clone(terminal=True, returncode=128)
        self.assertEqual(visible(out), "")
        self.assertIn("fatal: no such ref", err)
        self.assertIn("Failed to clone o/n (r)", err)

    def test_old_python_gets_a_clear_message(self):
        with patch.object(bootstrap.sys, "version_info", (3, 9, 0)):
            self.assertIn("needs Python 3.10", errors_of(bootstrap.main, []))

    def test_old_pythons_can_parse_it(self):
        # So that they reach the version check instead of a SyntaxError.
        source = (ROOT / "pull.py").read_text(encoding="utf-8")
        ast.parse(source, feature_version=(3, 6))


if __name__ == "__main__":
    unittest.main()
