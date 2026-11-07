"""Tests for pull.py, the bootstrap that runs omadotfile.

Nothing is cloned or installed: omadotfile.legacy.main is replaced by a mock.
"""

import ast
import contextlib
import importlib.util
import io
from pathlib import Path
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
import omadotfile.legacy  # noqa: E402  (the module run() imports)


def errors_of(function, *args) -> str:
    with contextlib.redirect_stderr(io.StringIO()) as err, \
            contextlib.redirect_stdout(io.StringIO()), \
            unittest.TestCase().assertRaises(SystemExit):
        function(*args)
    return err.getvalue()


class BootstrapTests(unittest.TestCase):
    def test_repo_argument_is_taken_out_and_the_rest_passed_on(self):
        self.assertEqual(bootstrap.split_repo_arg(["--oauth", "--repo", "/x", "--all"]),
                         ("/x", ["--oauth", "--all"]))
        self.assertEqual(bootstrap.split_repo_arg(["--repo=/y"]), ("/y", []))
        self.assertEqual(bootstrap.split_repo_arg(["--oauth"]), (None, ["--oauth"]))
        self.assertIn("--repo needs a path", errors_of(bootstrap.split_repo_arg, ["--repo"]))

    def test_local_checkout_runs_its_own_package(self):
        with patch.object(omadotfile.legacy, "main") as main:
            bootstrap.main(["--repo", str(ROOT), "--oauth"])
        main.assert_called_once_with(["--oauth"], repo_path=ROOT)

    def test_checkout_without_the_package_is_refused_in_one_line(self):
        with tempfile.TemporaryDirectory() as directory:
            message = errors_of(bootstrap.run, Path(directory), [])
        self.assertIn("has no omadotfile package", message)
        self.assertNotIn("Traceback", message)

    def test_old_python_gets_a_clear_message(self):
        with patch.object(bootstrap.sys, "version_info", (3, 9, 0)):
            self.assertIn("needs Python 3.10", errors_of(bootstrap.main, []))

    def test_old_pythons_can_parse_it(self):
        # So that they reach the version check instead of a SyntaxError.
        source = (ROOT / "pull.py").read_text(encoding="utf-8")
        ast.parse(source, feature_version=(3, 6))


if __name__ == "__main__":
    unittest.main()
