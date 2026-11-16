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
        self.plugin = self.home / ".gemini" / "config" / "plugins" / "oma-dotfile"
        self.enterContext(patch.object(agy, "WINDOWS", True))

    def install(self, python: str, **env: str) -> None:
        AGENTS["agy"].run(make_context(self.home, found=("agy",), python=python, env=env))

    def wrapper(self) -> str:
        # ASCII only: cmd reads a batch file in the console's code page, which can be any.
        return (self.plugin / "scripts" / "gotify-notify.cmd").read_bytes().decode("ascii")

    def test_the_command_is_one_word_and_the_wrapper_quotes_the_interpreter(self):
        self.install(r"C:\Program Files\Python314\python.exe")
        hooks = json.loads((self.plugin / "hooks.json").read_text(encoding="utf-8"))
        # No quote or space, whatever agy does to it on its way to cmd /c.
        self.assertEqual(hooks["oma-dotfile-gotify-notify"]["Stop"][0]["command"], r"scripts\gotify-notify.cmd")
        self.assertEqual(self.wrapper().splitlines()[0], "@echo off")
        self.assertIn('"C:\\Program Files\\Python314\\python.exe" "%~dp0gotify-notify.py"\r\n', self.wrapper())

    def test_a_percent_sign_is_not_a_variable(self):
        self.install(r"C:\100% py\python.exe")
        self.assertIn('"C:\\100%% py\\python.exe"', self.wrapper())

    def test_letters_outside_ascii_are_left_to_a_variable_cmd_expands(self):
        # The longest dir that holds the interpreter wins; names are matched in any case.
        self.install(r"C:\Users\Zoë Example\AppData\Local\Programs\100% Py\python.exe",
                     USERPROFILE=r"C:\Users\Zoë Example", LocalAppData="C:\\Users\\zoë example\\AppData\\Local\\")
        self.assertIn('"%LOCALAPPDATA%\\Programs\\100%% Py\\python.exe"', self.wrapper())

    def test_an_interpreter_no_variable_can_name_gets_no_hook(self):
        self.install(r"D:\张三\python.exe", USERPROFILE=r"C:\Users\张三")
        self.assertFalse((self.plugin / "hooks.json").exists())
        self.assertFalse((self.plugin / "scripts" / "gotify-notify.cmd").exists())
        self.assertTrue((self.plugin / "rules" / "AGENTS.md").is_file())
        (warning,) = self.console.warnings
        self.assertIn("Gotify hook is not installed", warning)
