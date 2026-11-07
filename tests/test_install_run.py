"""Whole installs into a temporary HOME, with stand-in agent CLIs; nothing real is touched.

The stand-ins answer the plugin and skills commands like the real CLIs would and keep their
state under the temporary HOME. PATH holds only them, git and python3, so no real agent CLI
can run; `git ls-remote` is replaced, so nothing goes to the network.
"""

import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

from omadotfile import cli
from omadotfile.features import skills
from support import ROOT, TestCase

# Each stand-in records its argv in $STUB_LOG and its state in marker files.
STUB_PRELUDE = f"""#!{sys.executable}
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ["STUB_LOG"], "a") as log:
    log.write(json.dumps([Path(sys.argv[0]).name, *args]) + "\\n")
"""

CODEX_STUB = STUB_PRELUDE + textwrap.dedent("""
    home = Path(os.environ["CODEX_HOME"])
    marker = home / ".stub-wakatime"
    if args[:2] == ["plugin", "list"]:
        installed = [{"pluginId": "codex-cli-wakatime@wakatime", "installed": True, "enabled": True}]
        print(json.dumps({"installed": installed if marker.exists() else []}))
    elif args[:3] == ["plugin", "marketplace", "list"]:
        print(json.dumps({"marketplaces": []}))
    elif args[:2] == ["plugin", "add"]:
        marker.touch()
        print("{}")
    else:
        print("{}")
""")

CLAUDE_STUB = STUB_PRELUDE + textwrap.dedent("""
    home = Path(os.environ["CLAUDE_CONFIG_DIR"])
    marker = home / ".stub-wakatime"
    if args == ["plugin", "list", "--json"]:
        entry = {"id": "claude-code-wakatime@wakatime", "enabled": True}
        print(json.dumps([entry] if marker.exists() else []))
    elif args[:3] == ["plugin", "marketplace", "list"]:
        print("[]")
    elif args[:2] == ["plugin", "install"]:
        marker.touch()
        print(json.dumps({"outcome": "ok"}))
""")

NPX_STUB = STUB_PRELUDE + textwrap.dedent("""
    # npx -y skills@V add SOURCE -g -a AGENT... -s NAME... -y --json
    source = args[3]
    agents = args[args.index("-a") + 1:args.index("-s")]
    names = args[args.index("-s") + 1:args.index("-y", args.index("-s"))]
    if names == ["*"]:
        names = ["every-skill"]
    lock_path = Path(os.environ["XDG_STATE_HOME"]) / "skills" / ".skill-lock.json"
    lock = json.loads(lock_path.read_text()) if lock_path.exists() else {"skills": {}}
    for name in names:
        dirs = [Path.home() / ".agents" / "skills"]
        if "claude-code" in agents:
            dirs.append(Path(os.environ["CLAUDE_CONFIG_DIR"]) / "skills")
        for directory in dirs:
            (directory / name).mkdir(parents=True, exist_ok=True)
            (directory / name / "SKILL.md").write_text(name)
        lock["skills"][name] = {"source": source.partition("#")[0]}
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(json.dumps(lock))
    print(json.dumps([{"name": name, "status": "installed"} for name in names]))
""")

COMMIT = "0123456789abcdef0123456789abcdef01234567"


class InstallRunTests(TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.home = self.root / "home"
        self.home.mkdir()
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        for name, script in (("codex", CODEX_STUB), ("claude", CLAUDE_STUB), ("npx", NPX_STUB)):
            (bin_dir / name).write_text(script)
            (bin_dir / name).chmod(0o755)
        for name in ("opencode", "omo", "omp"):
            (bin_dir / name).write_text("#!/bin/sh\n")
            (bin_dir / name).chmod(0o755)
        for name in ("git", "python3"):
            (bin_dir / name).symlink_to(shutil.which(name))
        (self.home / ".config" / "tokscale").mkdir(parents=True)
        self.log = self.root / "stub.log"
        self.env = {
            "HOME": str(self.home),
            "PATH": str(bin_dir),
            "GIT_CONFIG_GLOBAL": str(self.root / "gitconfig"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "XDG_STATE_HOME": str(self.root / "state"),
            "STUB_LOG": str(self.log),
            "CODEX_BASE_URL": "https://gateway.example.invalid/v1",
            "CODEX_API_TOKEN": "test-token",
            "GITHUB_PERSONAL_ACCESS_TOKEN": "test-pat",
            "WAKATIME_API_KEY": "test-wakatime-key",
        }
        # The process env is what PATH lookups (shutil.which) and Path.home() see.
        self.enterContext(patch.dict(os.environ, self.env, clear=True))
        self.enterContext(patch.object(skills, "ls_remote_commit", lambda ctx, source: COMMIT))

    def install(self, *argv: str):
        with contextlib.redirect_stdout(io.StringIO()) as out, \
                contextlib.redirect_stderr(io.StringIO()) as err:
            ctx = cli.main(list(argv), repo=ROOT, env=self.env, home=self.home)
        return ctx, out.getvalue(), err.getvalue()

    def stub_calls(self) -> list[list[str]]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_every_agent_is_detected_and_installed(self):
        ctx, out, err = self.install()
        self.assertEqual(ctx.found, frozenset(cli.AGENTS))
        self.assertNotIn("         skipped: ", err)  # no step is skipped
        self.assertNotIn("Traceback", err)
        self.assertIn("[9/9]", out)
        for path in (".config/opencode/opencode.jsonc", ".config/opencode/AGENTS.md",
                     ".omo/omo.jsonc", ".omo/agent/models.json", ".omp/agent/models.yml",
                     ".codex/config.toml", ".claude/rules/oma-dotfile.md",
                     ".claude/skills/gotify-notify/hooks/hooks.json", ".claude/settings.json",
                     ".config/git/hooks/commit-msg", ".config/tokscale/settings.json",
                     ".wakatime.cfg", ".agents/skills/github-cli/SKILL.md"):
            self.assertTrue((self.home / path).is_file(), path)
        self.assertTrue((self.home / ".codex" / ".stub-wakatime").exists())
        self.assertTrue((self.home / ".claude" / ".stub-wakatime").exists())

    def test_second_run_changes_nothing(self):
        first, _, _ = self.install("--oauth")
        self.assertTrue(first.files.changed)
        calls = len(self.stub_calls())

        second, out, _ = self.install("--oauth")

        self.assertEqual(second.files.changed, [])
        self.assertEqual(list(self.home.rglob("*.bak-*")), [])
        self.assertIn("Codex WakaTime plugin already installed; skip", out)
        self.assertIn("Claude Code WakaTime plugin already installed; skip", out)
        # Only the listings run again: no plugin is re-added and no skill re-installed.
        rerun = self.stub_calls()[calls:]
        self.assertFalse([call for call in rerun if "add" in call or "install" in call], rerun)

    def test_changed_user_config_is_backed_up_once(self):
        self.install()
        agents_md = self.home / ".config" / "opencode" / "AGENTS.md"
        agents_md.write_text("edited by hand\n")

        ctx, _, _ = self.install()

        self.assertEqual(ctx.files.changed, [agents_md])
        backups = list(agents_md.parent.glob("AGENTS.md.bak-*"))
        self.assertEqual([path.read_text() for path in backups], ["edited by hand\n"])

    def test_missing_required_repo_file_exits(self):
        repo = self.root / "repo"
        repo.mkdir()
        (repo / "opencode.jsonc").write_text("{}")
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()) as err, \
                self.assertRaises(SystemExit) as raised:
            cli.main([], repo=repo, env=self.env, home=self.home)
        self.assertEqual(raised.exception.code, 1)
        self.assertIn("Required repository file is missing: omo.jsonc", err.getvalue())
        self.assertFalse((self.home / ".config" / "opencode").exists())


if __name__ == "__main__":
    unittest.main()
