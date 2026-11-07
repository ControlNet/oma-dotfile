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
DROP = ROOT / "git-hooks" / "drop-claude-attribution"
LFS_HOOK = ('#!/bin/sh\ncommand -v git-lfs >/dev/null 2>&1 || { echo >&2 "\\nThis repository is '
            'configured for Git LFS but \'git-lfs\' was not found on your path.\\n"; exit 2; }\n'
            'git lfs {name} "$@"\n')


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
        self.default = self.home / ".config" / "git" / "hooks"

    def install(self) -> str:
        return quiet(pull.ensure_git_hooks, ROOT, "test")

    def hooks_path(self) -> str:
        return subprocess.run(["git", "config", "--global", "--get", "core.hooksPath"],
                              capture_output=True, text=True).stdout.strip()

    def set_hooks_path(self, value: str) -> None:
        subprocess.run(["git", "config", "--global", "core.hooksPath", value], check=True)

    def assert_chained(self, hooks: Path, names=None) -> None:
        for name in names or pull.GIT_CHAINED_HOOKS:
            hook = hooks / name
            self.assertEqual(hook.read_bytes(), CHAIN.read_bytes(), name)
            self.assertTrue(hook.stat().st_mode & stat.S_IXUSR, name)
        self.assertEqual((hooks / "drop-claude-attribution").read_bytes(), DROP.read_bytes())

    def backups(self, hooks: Path) -> list[str]:
        return sorted(path.name.split(".bak-")[0] for path in hooks.glob("*.bak-*"))

    def test_chained_hooks_cover_commit_lfs_and_receive_hooks(self):
        for name in ("commit-msg", "pre-commit", "prepare-commit-msg", "pre-push", "post-checkout",
                     "post-commit", "post-merge", "post-rewrite", "pre-receive", "post-receive"):
            self.assertIn(name, pull.GIT_CHAINED_HOOKS)
        # These run on every ref update or speak a protocol over stdin and stdout, and
        # push-to-checkout replaces git's own worktree update merely by existing.
        for name in ("reference-transaction", "post-index-change", "proc-receive", "push-to-checkout"):
            self.assertNotIn(name, pull.GIT_CHAINED_HOOKS)

    def test_unset_hooks_path_is_set_to_the_default_dir(self):
        output = self.install()
        self.assertEqual(self.hooks_path(), str(self.default))
        self.assert_chained(self.default)
        self.assertIn("core.hooksPath", output)

    def test_existing_hooks_path_is_used_and_kept(self):
        self.set_hooks_path("~/my-hooks")
        self.install()
        self.assertEqual(self.hooks_path(), "~/my-hooks")
        self.assert_chained(self.home / "my-hooks")
        self.assertFalse(self.default.exists())

    def test_git_lfs_hooks_and_the_old_commit_msg_are_backed_up_then_replaced(self):
        hooks = self.home / "hooks"
        hooks.mkdir()
        for name in pull.GIT_LFS_HOOKS:
            _ = (hooks / name).write_text(LFS_HOOK.replace("{name}", name), encoding="utf-8")
        _ = (hooks / "commit-msg").write_bytes(DROP.read_bytes())
        self.set_hooks_path(str(hooks))
        self.install()
        self.assert_chained(hooks)
        self.assertEqual(self.backups(hooks), sorted(["commit-msg", *pull.GIT_LFS_HOOKS]))

    def test_unknown_commit_msg_is_backed_up_then_replaced(self):
        hooks = self.home / "hooks"
        hooks.mkdir()
        _ = (hooks / "commit-msg").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self.set_hooks_path(str(hooks))
        self.install()
        self.assert_chained(hooks, ["commit-msg"])
        backup = next(hooks.glob("commit-msg.bak-*"))
        self.assertEqual(backup.read_text(encoding="utf-8"), "#!/bin/sh\nexit 0\n")

    def test_other_unknown_hooks_are_kept(self):
        hooks = self.home / "hooks"
        hooks.mkdir()
        _ = (hooks / "pre-push").write_text("#!/bin/sh\nmy-own-check\n", encoding="utf-8")
        link = hooks / "pre-commit"
        link.symlink_to(self.home / "elsewhere")
        self.set_hooks_path(str(hooks))
        output = self.install()
        self.assertEqual((hooks / "pre-push").read_text(encoding="utf-8"), "#!/bin/sh\nmy-own-check\n")
        self.assertTrue(link.is_symlink())
        self.assertFalse((self.home / "elsewhere").exists())
        self.assertEqual(self.backups(hooks), [])
        self.assertIn("pre-commit, pre-push", output)
        self.assert_chained(hooks, ["commit-msg", "post-merge"])

    def test_commit_msg_symlink_is_not_written_through(self):
        hooks = self.home / "hooks"
        hooks.mkdir()
        target = self.home / "dotfiles-commit-msg"
        _ = target.write_text("#!/bin/sh\n", encoding="utf-8")
        (hooks / "commit-msg").symlink_to(target)
        self.set_hooks_path(str(hooks))
        output = self.install()
        self.assertEqual(target.read_text(encoding="utf-8"), "#!/bin/sh\n")
        self.assertIn("commit-msg", output)

    def test_earlier_managed_version_is_replaced_without_a_backup(self):
        hooks = self.home / "hooks"
        hooks.mkdir()
        _ = (hooks / "pre-commit").write_text("#!/bin/sh\n# managed by oma-dotfile\nold\n", encoding="utf-8")
        self.set_hooks_path(str(hooks))
        self.install()
        self.assert_chained(hooks, ["pre-commit"])
        self.assertEqual(self.backups(hooks), [])

    def test_managed_push_to_checkout_from_an_earlier_version_is_removed(self):
        hooks = self.home / "hooks"
        hooks.mkdir()
        _ = (hooks / "push-to-checkout").write_bytes(CHAIN.read_bytes())
        self.set_hooks_path(str(hooks))
        self.install()
        self.assertFalse((hooks / "push-to-checkout").exists())

    def test_own_push_to_checkout_is_kept(self):
        hooks = self.home / "hooks"
        hooks.mkdir()
        _ = (hooks / "push-to-checkout").write_text("#!/bin/sh\ngit read-tree -u -m HEAD \"$1\"\n",
                                                   encoding="utf-8")
        self.set_hooks_path(str(hooks))
        self.install()
        self.assertTrue((hooks / "push-to-checkout").is_file())

    def test_second_run_changes_nothing(self):
        self.install()
        before = {path.name: path.stat().st_mtime_ns for path in self.default.iterdir()}
        output = self.install()
        after = {path.name: path.stat().st_mtime_ns for path in self.default.iterdir()}
        self.assertEqual(after, before)
        self.assertNotIn("core.hooksPath", output)

    def test_relative_hooks_path_is_not_touched(self):
        self.set_hooks_path(".githooks")
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

    def repo_hook(self, name: str, body: str, repo: Path | None = None) -> None:
        hook = (repo or self.repo) / ".git" / "hooks" / name
        _ = hook.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        hook.chmod(0o755)

    def message(self, cwd: Path | None = None) -> str:
        return self.git(cwd or self.repo, "log", "-1", "--format=%B").stdout

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

    def test_repo_pre_push_gets_its_arguments_and_stdin(self):
        remote = self.tmp / "remote.git"
        self.git(self.tmp, "init", "-q", "--bare", str(remote))
        self.git(self.repo, "commit", "-q", "--allow-empty", "-m", "D")
        self.repo_hook("pre-push", 'echo "args=$*"\nsed "s/^/stdin: /"\n')
        result = self.git(self.repo, "push", str(remote), "HEAD:refs/heads/main")
        head = self.git(self.repo, "rev-parse", "HEAD").stdout.strip()
        self.assertIn(f"args={remote} {remote}", result.stdout)
        self.assertIn(f"stdin: HEAD {head} refs/heads/main", result.stdout)

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
        _ = (hooks / "drop-claude-attribution").write_bytes(DROP.read_bytes())
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
        remote = self.tmp / "remote.git"
        self.git(self.tmp, "init", "-q", "--bare", str(remote))
        self.git(self.repo, "lfs", "track", "*.bin")
        data = os.urandom(3000)
        _ = (self.repo / "big.bin").write_bytes(data)
        self.git(self.repo, "add", ".gitattributes", "big.bin")
        self.git(self.repo, "commit", "-q", "-m", "lfs")
        self.repo_hook("pre-push", 'echo "repo pre-push saw $(cut -c1-4)"\n')
        # Git LFS finds its endpoint from a named remote, as in normal use.
        self.git(self.repo, "remote", "add", "origin", str(remote))
        result = self.git(self.repo, "push", "origin", "HEAD:refs/heads/main")
        self.assertIn("repo pre-push saw HEAD", result.stdout)
        self.assertTrue(any((remote / "lfs" / "objects").rglob("*")))
        clone = self.tmp / "clone"
        self.git(self.tmp, "clone", "-q", "-b", "main", str(remote), str(clone))
        self.assertEqual((clone / "big.bin").read_bytes(), data)

    def test_lfs_repo_without_git_lfs_refuses_to_push(self):
        # A PATH with git and the shell tools the hook uses, but no git-lfs.
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        for tool in ("git", "sh", "basename", "dirname", "cat", "head", "mktemp", "rm", "sed", "grep"):
            (bin_dir / tool).symlink_to(shutil.which(tool))
        (bin_dir / "python3").symlink_to(sys.executable)
        env = {**self.env, "PATH": str(bin_dir)}
        remote = self.tmp / "remote.git"
        self.git(self.tmp, "init", "-q", "--bare", str(remote))
        self.git(self.repo, "commit", "-q", "--allow-empty", "-m", "H")
        self.assertEqual(self.git(self.repo, "push", "-q", str(remote), "HEAD:refs/heads/a",
                                  env=env).returncode, 0)
        _ = (self.repo / ".gitattributes").write_text("*.bin filter=lfs diff=lfs merge=lfs -text\n",
                                                     encoding="utf-8")
        _ = (self.repo / "big.bin").write_bytes(b"data")
        self.git(self.repo, "add", ".gitattributes", "big.bin", env=env)
        self.git(self.repo, "commit", "-q", "-m", "I", env=env)
        result = self.git(self.repo, "push", "-q", str(remote), "HEAD:refs/heads/b", check=False, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("git-lfs", result.stderr)


if __name__ == "__main__":
    unittest.main()
