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
# Shaped like what versions 2ada252 to b182b57 installed: the chain script under every hook name,
# the commit-msg script that dropped attribution, and the hooks git-lfs writes.
CHAIN = b"#!/bin/sh\n# managed by oma-dotfile\nexec true\n"
DROP = b"#!/usr/bin/env python3\n# drops Claude attribution lines\n"
LFS = {name: f'#!/bin/sh\ngit lfs {name} "$@"\n'.encode() for name in
       ("pre-push", "post-checkout", "post-commit", "post-merge")}
CHAINED = ("applypatch-msg", "commit-msg", "post-checkout", "post-commit", "post-merge",
           "pre-commit", "pre-push", "push-to-checkout")


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

    def test_chain_hooks_of_earlier_versions_are_replaced(self):
        hooks = self.home / ".config" / "git" / "hooks"
        hooks.mkdir(parents=True)
        for name in CHAINED:
            _ = (hooks / name).write_bytes(CHAIN)
        (hooks / "pre-push.d").mkdir()
        _ = (hooks / "pre-push.d" / "git-lfs").write_bytes(LFS["pre-push"])
        self.install()
        self.assertEqual(sorted(path.name for path in hooks.iterdir()), ["commit-msg", "pre-push"])
        self.assert_installed(hooks / "commit-msg")
        self.assertEqual((hooks / "pre-push").read_bytes(), LFS["pre-push"])


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


class RemoveGitHookChainTests(unittest.TestCase):
    def setUp(self):
        self.hooks = Path(self.enterContext(tempfile.TemporaryDirectory())) / "hooks"
        self.hooks.mkdir()

    def remove(self) -> str:
        return quiet(pull.remove_git_hook_chain, self.hooks)

    def write(self, name: str, content: bytes) -> Path:
        path = self.hooks / name
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = path.write_bytes(content)
        path.chmod(0o755)
        return path

    def files(self) -> dict[str, bytes]:
        return {str(path.relative_to(self.hooks)): path.read_bytes()
                for path in sorted(self.hooks.rglob("*")) if path.is_file()}

    def chain(self) -> None:
        for name in CHAINED:
            _ = self.write(name, CHAIN)

    def test_drop_in_dirs_go_back_to_the_hooks_they_replaced(self):
        # What 18ea084 and later left: the old commit-msg and git-lfs's hooks in <name>.d/.
        self.chain()
        _ = self.write("commit-msg.d/drop-claude-attribution", DROP)
        for name, content in LFS.items():
            _ = self.write(f"{name}.d/git-lfs", content)
        _ = self.write("notes.txt", b"not a hook\n")
        output = self.remove()
        self.assertEqual(self.files(), {"commit-msg": DROP, **LFS, "notes.txt": b"not a hook\n"})
        self.assertEqual([path.name for path in self.hooks.iterdir() if path.is_dir()], [])
        self.assertTrue(os.access(self.hooks / "pre-push", os.X_OK))
        self.assertIn("put back commit-msg, post-checkout, post-commit, post-merge, pre-push", output)

    def test_a_hook_that_was_moved_aside_wins_and_other_files_are_kept(self):
        self.chain()
        _ = self.write("pre-push.d/previous", b"#!/bin/sh\nmy pre-push\n")
        _ = self.write("pre-push.d/git-lfs", LFS["pre-push"])
        _ = self.write("pre-commit.d/lint", b"#!/bin/sh\nmy lint\n")
        output = self.remove()
        self.assertEqual(self.files(), {"pre-push": b"#!/bin/sh\nmy pre-push\n",
                                        "pre-commit.d/lint": b"#!/bin/sh\nmy lint\n"})
        self.assertIn("pre-commit.d/lint", output)

    def test_backups_go_back_to_the_hooks_they_replaced(self):
        # What 2ada252 and 21567f0 left: replaced hooks backed up as <name>.bak-<stamp>.
        self.chain()
        _ = self.write("drop-claude-attribution", DROP)
        _ = self.write("commit-msg.bak-20261107-085000", b"#!/bin/sh\nolder\n")
        _ = self.write("commit-msg.bak-20261107-090000", b"#!/bin/sh\nnewer\n")
        _ = self.write("pre-push.bak-20261107-085000", LFS["pre-push"])
        _ = self.remove()
        self.assertEqual(self.files(), {"commit-msg": b"#!/bin/sh\nnewer\n",
                                        "commit-msg.bak-20261107-085000": b"#!/bin/sh\nolder\n",
                                        "pre-push": LFS["pre-push"]})

    def test_drop_script_becomes_commit_msg_when_nothing_else_was_there(self):
        self.chain()
        _ = self.write("drop-claude-attribution", DROP)
        _ = self.remove()
        self.assertEqual(self.files(), {"commit-msg": DROP})

    def test_hooks_of_your_own_are_left_alone(self):
        _ = self.write("commit-msg", DROP)
        _ = self.write("pre-commit.d/lint", b"#!/bin/sh\n")
        _ = self.write("drop-claude-attribution", DROP)
        before = self.files()
        self.assertEqual(self.remove(), "")
        self.assertEqual(self.files(), before)

    def test_second_run_does_nothing(self):
        self.chain()
        _ = self.write("commit-msg.d/drop-claude-attribution", DROP)
        _ = self.remove()
        after = self.files()
        self.assertEqual(self.remove(), "")
        self.assertEqual(self.files(), after)


class RetiredClaudePluginTests(unittest.TestCase):
    def setUp(self):
        self.claude = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def plugin(self, dir_name: str, manifest_name: str) -> Path:
        plugin = self.claude / "skills" / dir_name
        (plugin / ".claude-plugin").mkdir(parents=True)
        _ = (plugin / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"name": manifest_name}), encoding="utf-8")
        return plugin

    def test_installed_strip_attribution_plugin_is_removed(self):
        plugin = self.plugin("strip-attribution", "strip-attribution")
        quiet(pull.install_claude_plugins, ROOT, self.claude, "test")
        self.assertFalse(plugin.exists())
        self.assertTrue((self.claude / "skills" / "gotify-notify").is_dir())

    def test_other_dir_with_that_name_is_kept(self):
        plugin = self.plugin("strip-attribution", "my-own-plugin")
        quiet(pull.install_claude_plugins, ROOT, self.claude, "test")
        self.assertTrue(plugin.is_dir())


if __name__ == "__main__":
    unittest.main()
