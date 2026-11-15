"""Claude Code commit attribution tests.

Settings files, hook dirs and commit messages are synthetic and live in temporary
directories. Git runs for real, but against a temporary global config and HOME.
"""

import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from omadotfile.agents import claude
from omadotfile.core import proc
from omadotfile.core.proc import Runner
from omadotfile.console import use_console
from support import ROOT, WINDOWS, Recorder, TestCase, make_context

HOOK = ROOT / "config" / "git-hooks" / "commit-msg.py"
ATTRIBUTION = "Claude-Session: https://claude.ai/code/session_example"


def quiet(function, *args):
    """Call function with a Recorder bound; every line it printed, one per line."""
    with use_console(Recorder()) as printed:
        function(*args)
    return printed.text


class ClaudeAttributionTests(TestCase):
    def setUp(self):
        self.claude = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.settings = self.claude / "settings.json"
        self.ctx = make_context(self.claude / "home", backup=True)

    def install(self) -> str:
        return quiet(claude.ensure_attribution, self.ctx, self.claude)

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


class GitHookTests(TestCase):
    def setUp(self):
        self.home = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.gitconfig = self.home / ".gitconfig"
        env = {"HOME": str(self.home), "GIT_CONFIG_GLOBAL": str(self.gitconfig),
               "GIT_CONFIG_NOSYSTEM": "1"}
        self.enterContext(patch.dict(os.environ, env))
        os.environ.pop("XDG_CONFIG_HOME", None)

    def install(self, python: str = sys.executable) -> str:
        # A fresh context per run, like each install run, with the env it would snapshot.
        ctx = make_context(self.home, env=dict(os.environ), backup=True, stamp="test", python=python)
        return quiet(claude.ensure_commit_msg_hook, ctx)

    def commit(self, path: str | None = None) -> tuple[subprocess.CompletedProcess[str], str]:
        """Commit in a new repo through the installed hook; the result and the message kept."""
        repo = self.enterContext(tempfile.TemporaryDirectory())
        env = dict(os.environ) if path is None else {**os.environ, "PATH": path}
        git = ["git", "-C", repo, "-c", "user.name=T", "-c", "user.email=t@example.invalid"]
        subprocess.run([*git, "init", "-q"], check=True)
        result = subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", f"Subject\n\n{ATTRIBUTION}"],
                                capture_output=True, text=True, env=env)
        message = subprocess.run([*git, "log", "-1", "--format=%B"], capture_output=True, text=True).stdout
        return result, message

    def path_with_only_git(self) -> str:
        git = Path(shutil.which("git") or "git").resolve()
        if WINDOWS:
            # The dir Git for Windows puts on PATH, plus its usr\\bin, where the sh that runs
            # hooks lives (cmd\\git.exe does not add it when MSYSTEM is set, as under Git Bash).
            root = next(root for root in git.parents if (root / "cmd" / "git.exe").is_file())
            return os.pathsep.join([str(root / "cmd"), str(root / "usr" / "bin")])
        bare = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (bare / "git").symlink_to(git)
        return str(bare)

    def hooks_path(self) -> str:
        return subprocess.run(["git", "config", "--global", "--get", "core.hooksPath"],
                              capture_output=True, text=True).stdout.strip()

    def set_hooks_path(self, value: str) -> None:
        subprocess.run(["git", "config", "--global", "core.hooksPath", value], check=True)

    def assert_installed(self, hook: Path) -> None:
        # The hook git runs is a sh wrapper; the Python script next to it does the work.
        script = hook.with_name("commit-msg.py")
        self.assertEqual(script.read_bytes(), HOOK.read_bytes())
        wrapper = hook.read_text(encoding="utf-8")
        self.assertTrue(wrapper.startswith("#!/bin/sh\n"))
        self.assertIn(f"'{Path(sys.executable).as_posix()}'", wrapper)
        self.assertIn(f"'{script.as_posix()}'", wrapper)
        self.assertNotIn(b"\r", hook.read_bytes())  # Git's sh on Windows reads CRLF as part of the command
        if not WINDOWS:  # no execute bit there; Git for Windows runs the hook through sh
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

    def test_a_commit_goes_through_without_python_on_path(self):
        # A GUI client, an IDE or cron may commit with no python3 on PATH, and on Windows
        # python3 is often only the Store's alias; the hook runs the Python that installed it.
        with patch.object(Runner, "on_path", return_value=None):
            self.install()
        result, message = self.commit(self.path_with_only_git())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(message.strip(), "Subject")

    def test_a_missing_interpreter_never_blocks_a_commit(self):
        # Quotes and spaces in the path survive the wrapper's quoting.
        gone = str(self.home / "it's gone" / "python")
        self.install(python=gone)
        result, message = self.commit()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(ATTRIBUTION, message)
        self.assertIn("rerun pull.py", result.stderr)
        self.assertIn(Path(gone).as_posix(), result.stderr)

    def test_without_git_nothing_happens(self):
        with patch.object(proc.subprocess, "run", side_effect=FileNotFoundError("git")):
            output = self.install()
        self.assertFalse((self.home / ".config").exists())
        self.assertIn("git", output)


class HookBehaviourTests(TestCase):
    def test_claude_attribution_lines_are_dropped_and_the_rest_kept(self):
        message = Path(self.enterContext(tempfile.TemporaryDirectory())) / "COMMIT_EDITMSG"
        _ = message.write_text(
            "Fix the thing\n\nBody line.\nCo-Authored-By: Alice <alice@example.com>\n\n"
            "Co-Authored-By: Claude Opus <noreply@anthropic.com>\n"
            "🤖 Generated with [Claude Code](https://claude.com/claude-code)\n"
            "Claude-Session: https://claude.ai/code/session_example\n\n", encoding="utf-8")
        subprocess.run([sys.executable, str(HOOK), str(message)], check=True)
        self.assertEqual(message.read_text(encoding="utf-8"),
                         "Fix the thing\n\nBody line.\nCo-Authored-By: Alice <alice@example.com>\n")

    def run_hook(self, content: bytes) -> tuple[int, bytes]:
        message = Path(self.enterContext(tempfile.TemporaryDirectory())) / "COMMIT_EDITMSG"
        _ = message.write_bytes(content)
        result = subprocess.run([sys.executable, str(HOOK), str(message)], capture_output=True)
        return result.returncode, message.read_bytes()

    def test_a_message_without_attribution_is_left_byte_for_byte(self):
        # Form feed, U+2028, NEL, CRLF and trailing blank lines are the user's to keep.
        content = "Subject\r\n\r\nform\ffeed, line sep, next\u0085line\n\n\n".encode("utf-8")
        self.assertEqual(self.run_hook(content), (0, content))

    def test_bytes_that_are_not_utf8_pass_through(self):
        # `git commit -v` puts the staged diff below the scissors line; it may be in any encoding.
        scissors = b"# ------------------------ >8 ------------------------\n"
        diff = b"+caf\xe9\n+Co-Authored-By: Claude <noreply@anthropic.com>\n"
        content = (b"Caf\xe9 fix\n\nCo-Authored-By: Claude Opus <noreply@anthropic.com>\n\n"
                   + scissors + diff)
        self.assertEqual(self.run_hook(content), (0, b"Caf\xe9 fix\n" + scissors + diff))

    def test_a_missing_message_file_does_not_block_the_commit(self):
        missing = Path(self.enterContext(tempfile.TemporaryDirectory())) / "absent"
        result = subprocess.run([sys.executable, str(HOOK), str(missing)], capture_output=True)
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
