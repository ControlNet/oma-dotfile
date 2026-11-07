"""Claude Code commit attribution tests.

Settings files, hook dirs and commit messages are synthetic and live in temporary
directories. Git runs for real, but against a temporary global config and HOME.
"""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pull_commit_attribution", ROOT / "pull.py")
assert SPEC is not None and SPEC.loader is not None
pull = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pull)

HOOK = ROOT / "git-hooks" / "commit-msg"


def quiet(function, *args):
    with contextlib.redirect_stdout(io.StringIO()) as out, \
            contextlib.redirect_stderr(io.StringIO()) as err:
        function(*args)
    return out.getvalue() + err.getvalue()


class ClaudeAttributionTests(unittest.TestCase):
    def setUp(self):
        self.claude = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.settings = self.claude / "settings.json"
        self.enterContext(patch.object(pull, "NO_BACKUP", False))

    def install(self) -> str:
        return quiet(pull.ensure_claude_attribution, self.claude, "test")

    def read(self) -> dict:
        return json.loads(self.settings.read_text(encoding="utf-8"))

    def backups(self) -> list[Path]:
        return sorted(self.claude.glob("settings.json.bak-*"))

    def test_missing_settings_get_attribution_turned_off(self):
        self.install()
        self.assertEqual(self.read(), {"attribution": {"commit": "", "pr": ""}})

    def test_other_settings_are_kept(self):
        _ = self.settings.write_text(json.dumps({
            "model": "opus", "attribution": {"commit": "Made by a bot", "extra": 1},
            "includeCoAuthoredBy": True}), encoding="utf-8")
        self.install()
        self.assertEqual(self.read(), {"model": "opus", "includeCoAuthoredBy": True,
                                       "attribution": {"commit": "", "extra": 1, "pr": ""}})
        self.assertEqual(len(self.backups()), 1)

    def test_attribution_that_is_not_an_object_is_replaced(self):
        _ = self.settings.write_text(json.dumps({"attribution": "on"}), encoding="utf-8")
        self.install()
        self.assertEqual(self.read()["attribution"], {"commit": "", "pr": ""})

    def test_already_off_leaves_the_file_alone(self):
        text = '{\n  "attribution": {"pr": "", "commit": ""}\n}\n'
        _ = self.settings.write_text(text, encoding="utf-8")
        self.install()
        self.assertEqual(self.settings.read_text(encoding="utf-8"), text)
        self.assertEqual(self.backups(), [])

    def test_unreadable_settings_are_left_alone(self):
        for text in ("{not json", "[]"):
            _ = self.settings.write_text(text, encoding="utf-8")
            output = self.install()
            self.assertEqual(self.settings.read_text(encoding="utf-8"), text)
            self.assertIn("settings.json", output)


class GitHookTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.gitconfig = self.home / ".gitconfig"
        env = {"HOME": str(self.home), "GIT_CONFIG_GLOBAL": str(self.gitconfig),
               "GIT_CONFIG_NOSYSTEM": "1"}
        self.enterContext(patch.dict(os.environ, env))
        os.environ.pop("XDG_CONFIG_HOME", None)
        self.enterContext(patch.object(pull, "NO_BACKUP", False))

    def install(self) -> str:
        return quiet(pull.ensure_git_commit_msg_hook, ROOT, "test")

    def hooks_path(self) -> str:
        return subprocess.run(["git", "config", "--global", "--get", "core.hooksPath"],
                              capture_output=True, text=True).stdout.strip()

    def set_hooks_path(self, value: str) -> None:
        subprocess.run(["git", "config", "--global", "core.hooksPath", value], check=True)

    def assert_installed(self, hook: Path) -> None:
        self.assertEqual(hook.read_bytes(), HOOK.read_bytes())
        self.assertTrue(hook.stat().st_mode & stat.S_IXUSR)

    def test_unset_hooks_path_is_set_to_the_default_dir(self):
        default = self.home / ".config" / "git" / "hooks"
        output = self.install()
        self.assertEqual(self.hooks_path(), str(default))
        self.assert_installed(default / "commit-msg")
        self.assertIn("core.hooksPath", output)

    def test_existing_hooks_path_is_used_and_kept(self):
        self.set_hooks_path("~/my-hooks")
        self.install()
        self.assertEqual(self.hooks_path(), "~/my-hooks")
        self.assert_installed(self.home / "my-hooks" / "commit-msg")
        self.assertFalse((self.home / ".config" / "git" / "hooks").exists())

    def test_different_hook_is_backed_up_then_replaced(self):
        hooks = self.home / "hooks"
        hooks.mkdir()
        _ = (hooks / "commit-msg").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        _ = (hooks / "pre-push").write_text("lfs\n", encoding="utf-8")
        self.set_hooks_path(str(hooks))
        self.install()
        self.assert_installed(hooks / "commit-msg")
        backups = list(hooks.glob("commit-msg.bak-*"))
        self.assertEqual([path.read_text(encoding="utf-8") for path in backups], ["#!/bin/sh\nexit 0\n"])
        self.assertEqual((hooks / "pre-push").read_text(encoding="utf-8"), "lfs\n")

    def test_same_hook_is_left_alone(self):
        self.install()
        hook = self.home / ".config" / "git" / "hooks" / "commit-msg"
        before = hook.stat().st_mtime_ns
        self.install()
        self.assertEqual(hook.stat().st_mtime_ns, before)
        self.assertEqual(list(hook.parent.glob("commit-msg.bak-*")), [])

    def test_relative_hooks_path_is_not_touched(self):
        self.set_hooks_path(".githooks")
        output = self.install()
        self.assertEqual(self.hooks_path(), ".githooks")
        self.assertFalse((self.home / ".githooks").exists())
        self.assertIn(".githooks", output)

    def test_without_python3_the_hook_is_not_installed(self):
        # The hook runs through `#!/usr/bin/env python3`; without it every commit would fail.
        with patch.object(pull.shutil, "which", return_value=None):
            output = self.install()
        self.assertEqual(self.hooks_path(), "")
        self.assertFalse((self.home / ".config").exists())
        self.assertIn("python3", output)

    def test_without_git_nothing_happens(self):
        with patch.object(pull.subprocess, "run", side_effect=FileNotFoundError("git")):
            output = self.install()
        self.assertFalse((self.home / ".config").exists())
        self.assertIn("git", output)


@unittest.skipIf(sys.platform == "win32", "the hook runs through its python3 shebang")
class HookBehaviourTests(unittest.TestCase):
    def test_claude_attribution_lines_are_dropped_and_the_rest_kept(self):
        message = Path(self.enterContext(tempfile.TemporaryDirectory())) / "COMMIT_EDITMSG"
        _ = message.write_text(
            "Fix the thing\n\nBody line.\nCo-Authored-By: Alice <alice@example.com>\n\n"
            "Co-Authored-By: Claude Opus <noreply@anthropic.com>\n"
            "🤖 Generated with [Claude Code](https://claude.com/claude-code)\n"
            "Claude-Session: https://claude.ai/code/session_example\n\n", encoding="utf-8")
        subprocess.run([str(HOOK), str(message)], check=True)
        self.assertEqual(message.read_text(encoding="utf-8"),
                         "Fix the thing\n\nBody line.\nCo-Authored-By: Alice <alice@example.com>\n")


if __name__ == "__main__":
    unittest.main()
