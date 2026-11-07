"""Claude Code commit attribution tests.

Settings files and hook dirs are synthetic and live in temporary directories. Git runs
for real, but against a temporary global config and HOME.
"""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pull_commit_attribution", ROOT / "pull.py")
assert SPEC is not None and SPEC.loader is not None
pull = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pull)

# Shaped like what earlier versions installed: the chain script under every hook name,
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


class RemoveGitHookChainTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(self.enterContext(tempfile.TemporaryDirectory()))
        env = {"HOME": str(self.home), "GIT_CONFIG_GLOBAL": str(self.home / ".gitconfig"),
               "GIT_CONFIG_NOSYSTEM": "1"}
        self.enterContext(patch.dict(os.environ, env))
        self.hooks = self.home / ".config" / "git" / "hooks"
        self.hooks.mkdir(parents=True)
        subprocess.run(["git", "config", "--global", "core.hooksPath", str(self.hooks)], check=True)

    def remove(self) -> str:
        return quiet(pull.remove_git_hook_chain)

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
        self.assertIn("git config --global --unset core.hooksPath", output)
        hooks_path = subprocess.run(["git", "config", "--global", "core.hooksPath"],
                                    capture_output=True, text=True).stdout.strip()
        self.assertEqual(hooks_path, str(self.hooks))

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

    def test_no_global_hooks_dir_does_nothing(self):
        subprocess.run(["git", "config", "--global", "--unset", "core.hooksPath"], check=True)
        self.chain()
        self.assertEqual(self.remove(), "")
        self.assertEqual(len(self.files()), len(CHAINED))


if __name__ == "__main__":
    unittest.main()
