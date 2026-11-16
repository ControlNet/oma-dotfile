"""The Antigravity CLI plugin, installed into temporary homes only."""

import json
from pathlib import Path
import shlex
import tempfile
from unittest.mock import patch

from omadotfile.agents import agy
from omadotfile.cli import AGENTS
from support import ROOT, TestCase, make_context

PLUGIN_SRC = ROOT / "config" / "agy" / "plugins" / "oma-dotfile"


class AgyPluginTests(TestCase):
    def setUp(self):
        self.home = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.ctx = make_context(self.home, found=("agy",), python="/opt/py 3/bin/python3")
        self.agent = AGENTS["agy"]
        self.plugin = self.home / ".gemini" / "config" / "plugins" / "oma-dotfile"
        self.enterContext(patch.object(agy, "WINDOWS", False))

    def hook(self) -> dict[str, object]:
        hooks = json.loads((self.plugin / "hooks.json").read_text(encoding="utf-8"))
        (handler,) = hooks["oma-dotfile-gotify-notify"]["Stop"]
        return handler

    def test_the_plugin_carries_the_rules_and_the_hook(self):
        self.agent.run(self.ctx)
        self.assertEqual(self.agent.target_dir(self.ctx), self.plugin)
        self.assertEqual(json.loads((self.plugin / "plugin.json").read_text())["name"], "oma-dotfile")
        self.assertEqual((self.plugin / "rules" / "AGENTS.md").read_bytes(),
                         (ROOT / "config" / "_AGENTS.md").read_bytes())
        self.assertEqual((self.plugin / "scripts" / "gotify-notify.py").read_bytes(),
                         (PLUGIN_SRC / "scripts" / "gotify-notify.py").read_bytes())

    def test_the_hook_runs_the_installers_python_by_absolute_path(self):
        self.agent.run(self.ctx)
        # sh -c in the plugin dir: the quoted interpreter, then the script relative to it.
        self.assertEqual(shlex.split(self.hook()["command"]), ["/opt/py 3/bin/python3", "scripts/gotify-notify.py"])
        self.assertFalse((self.plugin / "scripts" / "gotify-notify.cmd").exists())

    def test_a_rerun_changes_and_says_nothing(self):
        self.agent.run(self.ctx)
        printed = len(self.console.lines)
        self.agent.run(self.ctx)
        self.assertEqual(len(self.console.lines), printed)
        self.assertEqual(self.ctx.files.changed, [self.plugin])

    def test_whatever_else_is_in_the_plugin_dir_goes(self):
        stale = self.plugin / "rules" / "OLD.md"
        stale.parent.mkdir(parents=True)
        stale.write_text("old")
        self.agent.run(self.ctx)
        self.assertFalse(stale.exists())

    def test_agys_shared_config_is_left_alone(self):
        config = self.home / ".gemini" / "config"
        config.mkdir(parents=True)
        mine = {"hooks.json": '{"herdr": {}}', "config.json": '{"plugins": {"oma-dotfile": {"enabled": false}}}'}
        for name, content in mine.items():
            (config / name).write_text(content)
        self.agent.run(self.ctx)
        for name, content in mine.items():
            self.assertEqual((config / name).read_text(), content)


class WindowsHookTests(TestCase):
    """cmd /c runs agy's hook on Windows; these render what the installer writes there."""

    def setUp(self):
        self.home = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.python = r"C:\Users\Zoë Example\100% py\python.exe"
        self.ctx = make_context(self.home, found=("agy",), python=self.python)
        self.plugin = self.home / ".gemini" / "config" / "plugins" / "oma-dotfile"
        self.enterContext(patch.object(agy, "WINDOWS", True))

    def test_the_command_is_one_word_and_the_wrapper_quotes_the_interpreter(self):
        with patch.object(agy, "oem_encoding", return_value="cp850"):
            AGENTS["agy"].run(self.ctx)
        hooks = json.loads((self.plugin / "hooks.json").read_text(encoding="utf-8"))
        # No quote or space, whatever agy does to it on its way to cmd /c.
        self.assertEqual(hooks["oma-dotfile-gotify-notify"]["Stop"][0]["command"], r"scripts\gotify-notify.cmd")
        # cmd reads a batch file in the OEM code page; % would start a variable.
        wrapper = (self.plugin / "scripts" / "gotify-notify.cmd").read_bytes().decode("cp850")
        self.assertIn('"C:\\Users\\Zoë Example\\100%% py\\python.exe" "%~dp0gotify-notify.py"\r\n', wrapper)
        self.assertTrue(wrapper.startswith("@echo off\r\n"))

    def test_an_interpreter_the_code_page_cannot_spell_gets_no_hook(self):
        ctx = make_context(self.home, found=("agy",), python=r"C:\Users\张三\python.exe")
        with patch.object(agy, "oem_encoding", return_value="cp437"):
            AGENTS["agy"].run(ctx)
        self.assertFalse((self.plugin / "hooks.json").exists())
        self.assertFalse((self.plugin / "scripts" / "gotify-notify.cmd").exists())
        self.assertTrue((self.plugin / "rules" / "AGENTS.md").is_file())
        (warning,) = self.console.warnings
        self.assertIn("cp437", warning)
