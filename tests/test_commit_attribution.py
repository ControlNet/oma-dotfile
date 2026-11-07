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
import shutil
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

CHAIN = ROOT / "git-hooks" / "chain"
DROP = ROOT / "git-hooks" / "commit-msg.d" / "drop-claude-attribution"
# Shaped like the hooks git-lfs writes; tests that need the real ones ask git-lfs.
FAKE_LFS = {name: f'#!/bin/sh\ngit lfs {name} "$@"\n'.encode() for name in
            ("pre-push", "post-checkout", "post-commit", "post-merge")}


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


def documented_git_hooks() -> list[str] | None:
    """Hook names from this git's githooks(5) page, or None without man pages."""
    try:
        page = subprocess.run(["man", "-P", "cat", "githooks"], capture_output=True, text=True,
                              env={**os.environ, "MANWIDTH": "200"}, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if page.returncode != 0 or "HOOKS" not in page.stdout:
        return None
    section = page.stdout.split("\nHOOKS", 1)[1].split("\nENVIRONMENT", 1)[0].split("\nGIT\n", 1)[0]
    names = [line.strip() for line in section.splitlines()
             if line.startswith("   ") and not line.startswith("    ")
             and line.strip().replace("-", "").isalnum() and line.strip().islower()]
    return names or None


class GitHookTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.gitconfig = self.home / ".gitconfig"
        env = {"HOME": str(self.home), "GIT_CONFIG_GLOBAL": str(self.gitconfig),
               "GIT_CONFIG_NOSYSTEM": "1"}
        self.enterContext(patch.dict(os.environ, env))
        os.environ.pop("XDG_CONFIG_HOME", None)
        self.default = self.home / ".config" / "git" / "hooks"
        # git-lfs is asked for its hooks in its own tests below.
        self.lfs = self.enterContext(patch.object(pull, "git_lfs_hooks", return_value=dict(FAKE_LFS)))
        self.enterContext(patch.object(pull, "git_lfs_installed", return_value=True))

    def install(self) -> str:
        return quiet(pull.ensure_git_hooks, ROOT, "test")

    def hooks_path(self) -> str:
        return subprocess.run(["git", "config", "--global", "--get", "core.hooksPath"],
                              capture_output=True, text=True).stdout.strip()

    def use_dir(self, name: str = "hooks") -> Path:
        hooks = self.home / name
        hooks.mkdir()
        subprocess.run(["git", "config", "--global", "core.hooksPath", str(hooks)], check=True)
        return hooks

    def assert_chained(self, hooks: Path) -> None:
        for name in pull.GIT_CHAINED_HOOKS:
            hook = hooks / name
            self.assertEqual(hook.read_bytes(), CHAIN.read_bytes(), name)
            self.assertTrue(hook.stat().st_mode & stat.S_IXUSR, name)
        drop = hooks / "commit-msg.d" / "drop-claude-attribution"
        self.assertEqual(drop.read_bytes(), DROP.read_bytes())
        self.assertTrue(drop.stat().st_mode & stat.S_IXUSR)

    def test_every_git_hook_is_chained_but_the_ones_that_cannot_be(self):
        # push-to-checkout replaces git's own worktree update just by existing,
        # post-index-change runs on every index write, and git finds fsmonitor-watchman
        # through core.fsmonitor, not by name.
        for name in pull.GIT_UNCHAINED_HOOKS:
            self.assertNotIn(name, pull.GIT_CHAINED_HOOKS)
        self.assertEqual(set(pull.GIT_UNCHAINED_HOOKS),
                         {"push-to-checkout", "post-index-change", "fsmonitor-watchman"})
        documented = documented_git_hooks()
        if documented is None:
            self.skipTest("githooks man page not available")
        self.assertEqual(sorted(set(documented) - set(pull.GIT_UNCHAINED_HOOKS)),
                         sorted(pull.GIT_CHAINED_HOOKS))

    def test_unset_hooks_path_is_set_to_the_default_dir(self):
        output = self.install()
        self.assertEqual(self.hooks_path(), str(self.default))
        self.assert_chained(self.default)
        self.assertIn("core.hooksPath", output)

    def test_existing_hooks_path_is_used_and_kept(self):
        subprocess.run(["git", "config", "--global", "core.hooksPath", "~/my-hooks"], check=True)
        self.install()
        self.assertEqual(self.hooks_path(), "~/my-hooks")
        self.assert_chained(self.home / "my-hooks")
        self.assertFalse(self.default.exists())

    def test_git_lfs_hooks_come_from_git_lfs(self):
        self.install()
        for name, content in FAKE_LFS.items():
            self.assertEqual((self.default / f"{name}.d" / "git-lfs").read_bytes(), content)
        self.assertFalse((self.default / "commit-msg.d" / "git-lfs").exists())

    def test_hooks_git_lfs_no_longer_writes_are_removed(self):
        self.install()
        self.lfs.return_value = {"pre-push": FAKE_LFS["pre-push"]}
        self.install()
        self.assertTrue((self.default / "pre-push.d" / "git-lfs").is_file())
        self.assertFalse((self.default / "post-merge.d" / "git-lfs").exists())

    def test_without_git_lfs_its_hooks_are_removed(self):
        self.install()
        with patch.object(pull, "git_lfs_installed", return_value=False):
            self.install()
        self.assertFalse(any(self.default.glob("*.d/git-lfs")))

    def test_git_lfs_that_fails_leaves_its_hooks_alone(self):
        self.install()
        self.lfs.return_value = None
        output = self.install()
        self.assertTrue((self.default / "pre-push.d" / "git-lfs").is_file())
        self.assertIn("git-lfs", output)

    def test_git_lfs_hook_this_list_does_not_chain_is_reported(self):
        self.lfs.return_value = {**FAKE_LFS, "push-to-checkout": b"#!/bin/sh\n"}
        output = self.install()
        self.assertFalse((self.default / "push-to-checkout.d").exists())
        self.assertIn("push-to-checkout", output)

    def test_own_global_hooks_move_into_their_dir_and_keep_running(self):
        hooks = self.use_dir()
        _ = (hooks / "pre-commit").write_text("#!/bin/sh\nmy-own-check\n", encoding="utf-8")
        (hooks / "pre-commit").chmod(0o755)
        _ = (hooks / "commit-msg").write_text("#!/bin/sh\nmy-msg-check\n", encoding="utf-8")
        output = self.install()
        self.assert_chained(hooks)
        for name, body in (("pre-commit", "my-own-check"), ("commit-msg", "my-msg-check")):
            moved = hooks / f"{name}.d" / "previous"
            self.assertEqual(moved.read_text(encoding="utf-8"), f"#!/bin/sh\n{body}\n")
            self.assertIn(f"{name}.d/previous", output)
        self.assertTrue((hooks / "pre-commit.d" / "previous").stat().st_mode & stat.S_IXUSR)

    def test_global_hooks_identical_to_what_is_installed_are_not_kept_twice(self):
        # This is how Git LFS's own hooks and the first commit-msg hook look.
        hooks = self.use_dir()
        for name, content in FAKE_LFS.items():
            _ = (hooks / name).write_bytes(content)
        _ = (hooks / "commit-msg").write_bytes(DROP.read_bytes())
        self.install()
        self.assert_chained(hooks)
        self.assertEqual(sorted(path.name for path in hooks.glob("*.d/*")),
                         sorted(["drop-claude-attribution", *(["git-lfs"] * len(FAKE_LFS))]))

    def test_second_previous_does_not_overwrite_the_first(self):
        hooks = self.use_dir()
        (hooks / "pre-commit.d").mkdir()
        _ = (hooks / "pre-commit.d" / "previous").write_text("first\n", encoding="utf-8")
        _ = (hooks / "pre-commit").write_text("second\n", encoding="utf-8")
        self.install()
        kept = sorted(path.read_text(encoding="utf-8") for path in (hooks / "pre-commit.d").iterdir())
        self.assertEqual(kept, ["first\n", "second\n"])

    def test_earlier_versions_leave_nothing_behind(self):
        hooks = self.use_dir()
        _ = (hooks / "pre-commit").write_text("#!/bin/sh\n# managed by oma-dotfile\nold\n", encoding="utf-8")
        _ = (hooks / "push-to-checkout").write_text("#!/bin/sh\n# managed by oma-dotfile\nold\n",
                                                   encoding="utf-8")
        _ = (hooks / "drop-claude-attribution").write_bytes(DROP.read_bytes())
        self.install()
        self.assert_chained(hooks)
        self.assertFalse((hooks / "pre-commit.d" / "previous").exists())
        self.assertFalse((hooks / "push-to-checkout").exists())
        self.assertFalse((hooks / "drop-claude-attribution").exists())

    def test_backups_left_by_earlier_versions_go_when_their_content_is_kept(self):
        hooks = self.use_dir()
        _ = (hooks / "pre-push.bak-20261107-085000").write_bytes(FAKE_LFS["pre-push"])
        _ = (hooks / "commit-msg.bak-20261107-085000").write_bytes(DROP.read_bytes())
        _ = (hooks / "commit-msg.bak-20261106-120000").write_text("#!/bin/sh\nmy-msg-check\n",
                                                                  encoding="utf-8")
        output = self.install()
        self.assertFalse((hooks / "pre-push.bak-20261107-085000").exists())
        self.assertFalse((hooks / "commit-msg.bak-20261107-085000").exists())
        # Different content was someone's own hook: it stays, and the output says so.
        self.assertTrue((hooks / "commit-msg.bak-20261106-120000").is_file())
        self.assertIn("commit-msg.bak-20261106-120000", output)
        self.assertIn("commit-msg.d/", output)

    def test_own_push_to_checkout_is_kept(self):
        hooks = self.use_dir()
        _ = (hooks / "push-to-checkout").write_text("#!/bin/sh\ngit read-tree -u -m HEAD \"$1\"\n",
                                                   encoding="utf-8")
        self.install()
        self.assertEqual((hooks / "push-to-checkout").read_text(encoding="utf-8"),
                         "#!/bin/sh\ngit read-tree -u -m HEAD \"$1\"\n")

    def test_symlinked_hook_is_kept_and_reported(self):
        hooks = self.use_dir()
        target = self.home / "dotfiles-commit-msg"
        _ = target.write_text("#!/bin/sh\n", encoding="utf-8")
        (hooks / "commit-msg").symlink_to(target)
        output = self.install()
        self.assertTrue((hooks / "commit-msg").is_symlink())
        self.assertEqual(target.read_text(encoding="utf-8"), "#!/bin/sh\n")
        self.assertIn("commit-msg", output)

    def test_second_run_changes_nothing(self):
        self.install()
        before = {path: path.stat().st_mtime_ns for path in self.default.rglob("*")}
        output = self.install()
        after = {path: path.stat().st_mtime_ns for path in self.default.rglob("*")}
        self.assertEqual(after, before)
        self.assertEqual(output, "")

    def test_relative_hooks_path_is_not_touched(self):
        subprocess.run(["git", "config", "--global", "core.hooksPath", ".githooks"], check=True)
        output = self.install()
        self.assertEqual(self.hooks_path(), ".githooks")
        self.assertFalse((self.home / ".githooks").exists())
        self.assertIn(".githooks", output)

    def test_without_python3_nothing_is_installed(self):
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


@unittest.skipUnless(shutil.which("git-lfs"), "git-lfs is not installed")
class GitLfsHooksTests(unittest.TestCase):
    def test_git_lfs_writes_its_hooks_without_touching_global_config(self):
        home = Path(self.enterContext(tempfile.TemporaryDirectory()))
        config = home / ".gitconfig"
        _ = config.write_text("[user]\n\tname = Test\n", encoding="utf-8")
        with patch.dict(os.environ, {"HOME": str(home), "GIT_CONFIG_GLOBAL": str(config),
                                     "GIT_CONFIG_NOSYSTEM": "1"}):
            hooks = pull.git_lfs_hooks()
        self.assertIsNotNone(hooks)
        self.assertIn("pre-push", hooks)
        self.assertIn(b'git lfs pre-push "$@"', hooks["pre-push"])
        self.assertEqual(config.read_text(encoding="utf-8"), "[user]\n\tname = Test\n")


class DropAttributionTests(unittest.TestCase):
    @unittest.skipIf(sys.platform == "win32", "runs the script through python3")
    def test_claude_attribution_lines_are_dropped_and_the_rest_kept(self):
        message = Path(self.enterContext(tempfile.TemporaryDirectory())) / "COMMIT_EDITMSG"
        _ = message.write_text(
            "Fix the thing\n\nBody line.\nCo-Authored-By: Alice <alice@example.com>\n\n"
            "Co-Authored-By: Claude Opus <noreply@anthropic.com>\n"
            "🤖 Generated with [Claude Code](https://claude.com/claude-code)\n"
            "Claude-Session: https://claude.ai/code/session_example\n\n", encoding="utf-8")
        subprocess.run([sys.executable, str(DROP), str(message)], check=True)
        self.assertEqual(message.read_text(encoding="utf-8"),
                         "Fix the thing\n\nBody line.\nCo-Authored-By: Alice <alice@example.com>\n")


@unittest.skipIf(sys.platform == "win32", "the chained hooks are POSIX sh scripts")
class ChainedHookBehaviourTests(unittest.TestCase):
    """Real git commits and pushes in temporary repos, through the installed global hooks."""

    CLAUDE = "Co-Authored-By: Claude Opus <noreply@anthropic.com>"

    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.env = {**os.environ, "HOME": str(self.home), "GIT_CONFIG_GLOBAL": str(self.home / ".gitconfig"),
                    "GIT_CONFIG_NOSYSTEM": "1"}
        self.env.pop("XDG_CONFIG_HOME", None)
        self.hooks = self.home / ".config" / "git" / "hooks"
        with patch.dict(os.environ, self.env, clear=True):
            quiet(pull.ensure_git_hooks, ROOT, "test")
        for key, value in (("user.name", "Test"), ("user.email", "test@example.com"),
                           ("init.defaultBranch", "main")):
            self.git(self.tmp, "config", "--global", key, value)
        self.repo = self.tmp / "repo"
        self.git(self.tmp, "init", "-q", str(self.repo))

    def git(self, cwd: Path, *args: str, check: bool = True, env=None) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=cwd, env=env or self.env, capture_output=True,
                              text=True, check=check)

    def hook(self, path: Path, body: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        path.chmod(0o755)

    def repo_hook(self, name: str, body: str) -> None:
        self.hook(self.repo / ".git" / "hooks" / name, body)

    def message(self, cwd: Path | None = None) -> str:
        return self.git(cwd or self.repo, "log", "-1", "--format=%B").stdout

    def bare_remote(self) -> Path:
        remote = self.tmp / "remote.git"
        self.git(self.tmp, "init", "-q", "--bare", str(remote))
        self.git(self.repo, "remote", "add", "origin", str(remote))
        return remote

    def test_claude_lines_are_dropped_without_repo_hooks(self):
        self.git(self.repo, "commit", "-q", "--allow-empty", "-m", f"A\n\n{self.CLAUDE}")
        self.assertEqual(self.message(), "A\n\n")

    def test_repo_commit_msg_runs_after_the_drop(self):
        self.repo_hook("commit-msg", 'grep -q Claude "$1" && exit 9\necho "Repo-Hook: ran" >> "$1"\n')
        self.git(self.repo, "commit", "-q", "--allow-empty", "-m", f"B\n\n{self.CLAUDE}")
        self.assertEqual(self.message(), "B\nRepo-Hook: ran\n\n")

    def test_failing_repo_pre_commit_blocks_the_commit(self):
        self.repo_hook("pre-commit", 'echo "lint failed" >&2\nexit 1\n')
        result = self.git(self.repo, "commit", "-q", "--allow-empty", "-m", "C", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("lint failed", result.stderr)

    def test_failing_global_drop_in_blocks_before_the_repo_hook(self):
        self.hook(self.hooks / "pre-commit.d" / "previous", 'echo "global check failed" >&2\nexit 3\n')
        self.repo_hook("pre-commit", 'echo "repo hook ran" >&2\n')
        result = self.git(self.repo, "commit", "-q", "--allow-empty", "-m", "C2", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("global check failed", result.stderr)
        self.assertNotIn("repo hook ran", result.stderr)

    def test_every_pre_push_hook_gets_the_same_stdin(self):
        self.bare_remote()
        self.git(self.repo, "commit", "-q", "--allow-empty", "-m", "D")
        self.hook(self.hooks / "pre-push.d" / "previous", 'sed "s/^/global: /"\n')
        self.repo_hook("pre-push", 'echo "args=$*"\nsed "s/^/repo: /"\n')
        result = self.git(self.repo, "push", "origin", "HEAD:refs/heads/main")
        head = self.git(self.repo, "rev-parse", "HEAD").stdout.strip()
        self.assertIn(f"global: HEAD {head} refs/heads/main", result.stdout)
        self.assertIn(f"repo: HEAD {head} refs/heads/main", result.stdout)
        self.assertIn("args=origin ", result.stdout)

    def test_repo_reference_transaction_hook_runs(self):
        self.repo_hook("reference-transaction", 'echo "$1" >> "$(git rev-parse --git-dir)/states"\n')
        self.git(self.repo, "commit", "-q", "--allow-empty", "-m", "R")
        states = (self.repo / ".git" / "states").read_text(encoding="utf-8").split()
        self.assertIn("committed", states)

    def test_worktree_runs_the_main_repo_hooks(self):
        self.git(self.repo, "commit", "-q", "--allow-empty", "-m", "E")
        self.repo_hook("commit-msg", 'echo "Repo-Hook: ran" >> "$1"\n')
        worktree = self.tmp / "wt"
        self.git(self.repo, "worktree", "add", "-q", str(worktree))
        self.git(worktree, "commit", "-q", "--allow-empty", "-m", "F")
        self.assertEqual(self.message(worktree), "F\nRepo-Hook: ran\n\n")

    def test_hooks_path_pointing_at_the_repo_hooks_does_not_loop(self):
        hooks = self.repo / ".git" / "hooks"
        _ = (hooks / "commit-msg").write_bytes(CHAIN.read_bytes())
        (hooks / "commit-msg").chmod(0o755)
        self.hook(hooks / "commit-msg.d" / "drop-claude-attribution", "")
        _ = (hooks / "commit-msg.d" / "drop-claude-attribution").write_bytes(DROP.read_bytes())
        self.git(self.repo, "config", "core.hooksPath", str(hooks))
        self.git(self.repo, "commit", "-q", "--allow-empty", "-m", f"G\n\n{self.CLAUDE}")
        self.assertEqual(self.message(), "G\n\n")

    def test_push_to_a_checked_out_branch_still_updates_its_worktree(self):
        target = self.tmp / "target"
        self.git(self.tmp, "init", "-q", str(target))
        self.git(target, "commit", "-q", "--allow-empty", "-m", "base")
        self.git(target, "config", "receive.denyCurrentBranch", "updateInstead")
        self.git(self.tmp, "clone", "-q", str(target), str(self.tmp / "work"))
        _ = (self.tmp / "work" / "new.txt").write_text("pushed\n", encoding="utf-8")
        self.git(self.tmp / "work", "add", "new.txt")
        self.git(self.tmp / "work", "commit", "-q", "-m", "J")
        self.git(self.tmp / "work", "push", "-q", "origin", "HEAD:main")
        self.assertEqual((target / "new.txt").read_text(encoding="utf-8"), "pushed\n")

    @unittest.skipUnless(shutil.which("git-lfs"), "git-lfs is not installed")
    def test_git_lfs_objects_are_uploaded_and_downloaded(self):
        for key, value in (("filter.lfs.clean", "git-lfs clean -- %f"),
                           ("filter.lfs.smudge", "git-lfs smudge -- %f"),
                           ("filter.lfs.process", "git-lfs filter-process"),
                           ("filter.lfs.required", "true")):
            self.git(self.tmp, "config", "--global", key, value)
        self.assertTrue((self.hooks / "pre-push.d" / "git-lfs").is_file())
        remote = self.bare_remote()
        self.git(self.repo, "lfs", "track", "*.bin")
        data = os.urandom(3000)
        _ = (self.repo / "big.bin").write_bytes(data)
        self.git(self.repo, "add", ".gitattributes", "big.bin")
        self.git(self.repo, "commit", "-q", "-m", "lfs")
        self.repo_hook("pre-push", 'echo "repo pre-push saw $(cut -c1-4)"\n')
        result = self.git(self.repo, "push", "origin", "HEAD:refs/heads/main")
        self.assertIn("repo pre-push saw HEAD", result.stdout)
        self.assertTrue(any((remote / "lfs" / "objects").rglob("*")))
        clone = self.tmp / "clone"
        self.git(self.tmp, "clone", "-q", "-b", "main", str(remote), str(clone))
        self.assertEqual((clone / "big.bin").read_bytes(), data)


if __name__ == "__main__":
    unittest.main()
