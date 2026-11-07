"""Whole installs into a temporary HOME, with stand-in agent CLIs; nothing real is touched.

The stand-ins answer the plugin and skills commands like the real CLIs would and keep their
state under the temporary HOME. PATH holds only them, git and python3, so no real agent CLI
can run; `git ls-remote` is replaced, so nothing goes to the network.
"""

import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

from omadotfile import cli
from omadotfile.context import Context
from omadotfile.features import skills
from support import ROOT, Recorder, TestCase

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

# A broken CLI: logs its argv like the others, then fails.
FAILING_STUB = STUB_PRELUDE + "sys.exit(1)\n"


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
        # The installer reads only the env passed to main; the process env is the sandbox too,
        # so anything that read os.environ instead would still not reach the real machine.
        self.enterContext(patch.dict(os.environ, self.env, clear=True))
        self.enterContext(patch.object(skills, "ls_remote_commit", lambda ctx, source: COMMIT))

    def install(self, *argv: str) -> tuple[Context, Recorder]:
        """Run the installer with a Recorder as its Console; the Context and what it printed."""
        printed = Recorder()
        ctx = cli.main(list(argv), repo=ROOT, env=self.env, home=self.home, console=printed)
        return ctx, printed

    def stub_calls(self) -> list[list[str]]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_every_agent_is_detected_and_installed(self):
        ctx, printed = self.install()
        self.assertEqual(ctx.found, frozenset(cli.AGENTS))
        # No step is skipped (console.step's skip line); a step's own optional parts may be.
        self.assertFalse([line for line in printed.warnings if line.startswith("         skipped: ")])
        self.assertTrue([line for line in printed.of("info") if line.startswith("[9/9] ")])
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
        first, _ = self.install("--oauth")
        self.assertTrue(first.files.changed)
        calls = len(self.stub_calls())

        second, printed = self.install("--oauth")

        self.assertEqual(second.files.changed, [])
        self.assertEqual(list(self.home.rglob("*.bak-*")), [])
        self.assertIn("Codex WakaTime plugin already installed; skip", printed.of("info"))
        self.assertIn("Claude Code WakaTime plugin already installed; skip", printed.of("info"))
        # Only the listings run again: no plugin is re-added and no skill re-installed.
        rerun = self.stub_calls()[calls:]
        self.assertFalse([call for call in rerun if "add" in call or "install" in call], rerun)

    def test_changed_user_config_is_backed_up_once(self):
        self.install()
        agents_md = self.home / ".config" / "opencode" / "AGENTS.md"
        agents_md.write_text("edited by hand\n")

        ctx, _ = self.install()

        self.assertEqual(ctx.files.changed, [agents_md])
        backups = list(agents_md.parent.glob("AGENTS.md.bak-*"))
        self.assertEqual([path.read_text() for path in backups], ["edited by hand\n"])

    def test_failing_agent_clis_are_warned_about_and_the_install_goes_on(self):
        for name in ("codex", "claude", "npx"):
            (self.root / "bin" / name).write_text(FAILING_STUB)

        _, printed = self.install()

        self.assertTrue([line for line in printed.of("info") if line.startswith("[9/9] ")])
        self.assertIn("Installation complete!", printed.of("success"))
        warnings = [line.replace(str(self.root / "bin"), "BIN") for line in printed.warnings]
        wakatime = "https://github.com/wakatime"
        skill_warnings = [line for line in warnings if "npx" in line or "installed from" in line]
        self.assertEqual([line for line in warnings if line not in skill_warnings
                          and ("codex" in line or "claude" in line or "marketplace" in line.lower())], [
            "BIN/codex plugin list --marketplace wakatime --json failed with exit code 1",
            "BIN/codex plugin marketplace list --json failed with exit code 1",
            f"BIN/codex plugin marketplace add {wakatime}/codex-cli-wakatime.git --json failed with exit code 1",
            "Stale marketplace state? Try: codex plugin marketplace remove wakatime",
            "BIN/claude plugin list --json failed with exit code 1",
            "BIN/claude plugin marketplace list --json failed with exit code 1",
            f"BIN/claude plugin marketplace add {wakatime}/claude-code-wakatime.git failed with exit code 1",
        ])
        # Each skills CLI run fails on its own; the next source is still tried.
        adds = [call for call in self.stub_calls() if call[0] == "npx"]
        self.assertEqual(len(skill_warnings), 2 * len(adds))
        for (failed, why), call in zip(zip(skill_warnings[::2], skill_warnings[1::2]), adds):
            self.assertEqual(failed, f"BIN/npx {' '.join(call[1:])} failed with exit code 1")
            self.assertRegex(why, rf"^(Not installed|Nothing installed) from {re.escape(call[4])}")
        # The listings fail softly: every CLI still gets as far as adding its marketplace.
        self.assertEqual([call[:4] for call in self.stub_calls() if call[0] != "npx"], [
            ["codex", "plugin", "list", "--marketplace"],
            ["codex", "plugin", "marketplace", "list"],
            ["codex", "plugin", "marketplace", "add"],
            ["claude", "plugin", "list", "--json"],
            ["claude", "plugin", "marketplace", "list"],
            ["claude", "plugin", "marketplace", "add"],
        ])

    def test_missing_required_repo_file_exits(self):
        repo = self.root / "repo"
        (repo / "config" / "opencode").mkdir(parents=True)
        (repo / "config" / "opencode" / "opencode.jsonc").write_text("{}")
        printed = Recorder()
        with self.assertRaises(SystemExit) as raised:
            cli.main([], repo=repo, env=self.env, home=self.home, console=printed)
        self.assertEqual(raised.exception.code, 1)
        self.assertEqual(printed.of("error"), ["Required repository file is missing: config/omo/omo.jsonc"])
        self.assertFalse((self.home / ".config" / "opencode").exists())


if __name__ == "__main__":
    unittest.main()
