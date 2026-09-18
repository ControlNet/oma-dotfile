"""Mocked agent CLI calls only; no marketplace is contacted and no user state changes."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pull", ROOT / "pull.py")
assert SPEC is not None and SPEC.loader is not None
pull = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pull)

EMPTY_PLUGIN_LIST = {"installed": [], "available": []}
INSTALLED_PLUGIN_LIST = {
    "installed": [
        {
            "pluginId": pull.WAKATIME_PLUGIN_ID,
            "installed": True,
            "enabled": True,
        }
    ],
    "available": [],
}
WAKATIME_MARKETPLACE_ENTRY = {
    "name": pull.WAKATIME_MARKETPLACE,
    "marketplaceSource": {
        "sourceType": "git",
        "source": pull.WAKATIME_MARKETPLACE_GIT_URL,
    },
}


CLAUDE_PLUGIN_LIST = [
    {"id": pull.CLAUDE_WAKATIME_PLUGIN_ID, "enabled": True, "version": "4.1.0"}
]
CLAUDE_MARKETPLACE_ENTRY = {
    "name": pull.WAKATIME_MARKETPLACE,
    "source": "git",
    "url": pull.CLAUDE_WAKATIME_MARKETPLACE_GIT_URL,
}


class FakeCli:
    """Answer agent plugin subcommands from a canned response table.

    A dict or list payload is serialized as JSON; a string is returned verbatim,
    which is how commands without JSON output behave.
    """

    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.calls: list[list[str]] = []
        self.envs: list[dict[str, str]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        self.envs.append(dict(kwargs.get("env") or {}))
        for key, payload in self.responses.items():
            if key in " ".join(argv):
                stdout = payload if isinstance(payload, str) else json.dumps(payload)
                return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="unexpected")


def run_ensure(responses: dict[str, object], codex_dir: Path, has_node: bool = True):
    fake = FakeCli(responses)
    executables = {"codex": "/usr/bin/codex"}
    if has_node:
        executables["node"] = "/usr/bin/node"
    with patch.object(pull.subprocess, "run", fake), \
            patch.object(pull.shutil, "which", lambda name: executables.get(name)):
        pull.ensure_codex_wakatime_plugin(codex_dir)
    return fake


def run_claude_ensure(responses: dict[str, object], claude_config_dir: Path):
    fake = FakeCli(responses)
    executables = {"claude": "/usr/bin/claude", "node": "/usr/bin/node"}
    with patch.object(pull.subprocess, "run", fake), \
            patch.object(pull.shutil, "which", lambda name: executables.get(name)):
        installed = pull.ensure_claude_wakatime_plugin(claude_config_dir)
    return fake, installed


class CodexWakatimePluginTests(unittest.TestCase):
    def test_first_install_adds_marketplace_then_plugin(self) -> None:
        # Given a Codex home without the WakaTime marketplace or plugin.
        with tempfile.TemporaryDirectory() as tmp:
            codex_dir = Path(tmp)
            (codex_dir / ".wakatime.cfg").write_text("[settings]\n", encoding="utf-8")
            with patch.object(pull, "get_wakatime_config_path",
                              lambda: codex_dir / ".wakatime.cfg"):
                # When the installer configures the plugin.
                fake = run_ensure(
                    {
                        "plugin list": EMPTY_PLUGIN_LIST,
                        "marketplace list": {"marketplaces": []},
                        "marketplace add": {"alreadyAdded": False},
                        "plugin add": {"pluginId": pull.WAKATIME_PLUGIN_ID},
                    },
                    codex_dir,
                )

            # Then it inspects state, adds the marketplace, and installs the plugin.
            self.assertEqual(
                fake.calls,
                [
                    ["codex", "plugin", "list", "--marketplace",
                     pull.WAKATIME_MARKETPLACE, "--json"],
                    ["codex", "plugin", "marketplace", "list", "--json"],
                    ["codex", "plugin", "marketplace", "add",
                     pull.WAKATIME_MARKETPLACE_GIT_URL, "--json"],
                    ["codex", "plugin", "add", pull.WAKATIME_PLUGIN_ID, "--json"],
                ],
            )
            # And every call honors the installer's Codex home.
            for env in fake.envs:
                self.assertEqual(env["CODEX_HOME"], str(codex_dir))

    def test_existing_marketplace_is_reused(self) -> None:
        # Given the marketplace already points at the documented source.
        with tempfile.TemporaryDirectory() as tmp:
            codex_dir = Path(tmp)
            fake = run_ensure(
                {
                    "plugin list": EMPTY_PLUGIN_LIST,
                    "marketplace list": {"marketplaces": [WAKATIME_MARKETPLACE_ENTRY]},
                    "plugin add": {"pluginId": pull.WAKATIME_PLUGIN_ID},
                },
                codex_dir,
            )
            # Then the installer skips marketplace add and installs the plugin.
            self.assertNotIn("add", fake.calls[1])
            self.assertEqual(
                fake.calls[-1],
                ["codex", "plugin", "add", pull.WAKATIME_PLUGIN_ID, "--json"],
            )

    def test_installed_and_enabled_plugin_is_skipped(self) -> None:
        # Given the plugin is already installed and enabled.
        with tempfile.TemporaryDirectory() as tmp:
            codex_dir = Path(tmp)
            fake = run_ensure({"plugin list": INSTALLED_PLUGIN_LIST}, codex_dir)
            # Then nothing beyond the state inspection runs.
            self.assertEqual(
                fake.calls,
                [["codex", "plugin", "list", "--marketplace",
                  pull.WAKATIME_MARKETPLACE, "--json"]],
            )

    def test_foreign_marketplace_source_is_not_replaced(self) -> None:
        # Given another marketplace already claims the wakatime name.
        with tempfile.TemporaryDirectory() as tmp:
            codex_dir = Path(tmp)
            foreign = {
                "name": pull.WAKATIME_MARKETPLACE,
                "marketplaceSource": {
                    "sourceType": "git",
                    "source": "https://example.test/other.git",
                },
            }
            fake = run_ensure(
                {
                    "plugin list": EMPTY_PLUGIN_LIST,
                    "marketplace list": {"marketplaces": [foreign]},
                },
                codex_dir,
            )
            # Then the installer stops instead of overwriting the user's source.
            self.assertEqual(len(fake.calls), 2)

    def test_missing_codex_cli_skips_quietly(self) -> None:
        # Given Codex is not installed on this machine.
        with tempfile.TemporaryDirectory() as tmp:
            fake = FakeCli({})
            with patch.object(pull.subprocess, "run", fake), \
                    patch.object(pull.shutil, "which", lambda name: None):
                pull.ensure_codex_wakatime_plugin(Path(tmp))
            # Then no Codex command is attempted.
            self.assertEqual(fake.calls, [])

    def test_failed_marketplace_add_stops_before_plugin_add(self) -> None:
        # Given the marketplace add fails, for example without network access.
        with tempfile.TemporaryDirectory() as tmp:
            codex_dir = Path(tmp)
            fake = run_ensure(
                {
                    "plugin list": EMPTY_PLUGIN_LIST,
                    "marketplace list": {"marketplaces": []},
                },
                codex_dir,
            )
            # Then the plugin install is not attempted.
            self.assertNotIn(
                ["codex", "plugin", "add", pull.WAKATIME_PLUGIN_ID, "--json"],
                fake.calls,
            )


class ClaudeWakatimePluginTests(unittest.TestCase):
    def test_first_install_adds_marketplace_then_plugin(self) -> None:
        # Given a Claude Code config directory without the marketplace or plugin.
        with tempfile.TemporaryDirectory() as tmp:
            claude_dir = Path(tmp)
            # When the installer configures the plugin.
            fake, installed = run_claude_ensure(
                {
                    "plugin list": [],
                    "marketplace list": [],
                    "marketplace add": "Successfully added marketplace: wakatime",
                    "plugin install": {"outcome": "ok"},
                },
                claude_dir,
            )

            # Then it inspects state, adds the marketplace, and installs the plugin.
            self.assertTrue(installed)
            self.assertEqual(
                fake.calls,
                [
                    ["claude", "plugin", "list", "--json"],
                    ["claude", "plugin", "marketplace", "list", "--json"],
                    ["claude", "plugin", "marketplace", "add",
                     pull.CLAUDE_WAKATIME_MARKETPLACE_GIT_URL],
                    ["claude", "plugin", "install", pull.CLAUDE_WAKATIME_PLUGIN_ID, "--json"],
                ],
            )
            # And every call honors the installer's Claude Code config directory.
            for env in fake.envs:
                self.assertEqual(env["CLAUDE_CONFIG_DIR"], str(claude_dir))

    def test_marketplace_add_is_not_asked_for_json(self) -> None:
        # Given the marketplace add subcommand, which rejects --json.
        with tempfile.TemporaryDirectory() as tmp:
            fake, _ = run_claude_ensure(
                {
                    "plugin list": [],
                    "marketplace list": [],
                    "marketplace add": "Successfully added marketplace: wakatime",
                    "plugin install": {"outcome": "ok"},
                },
                Path(tmp),
            )
            # Then only its exit code is used.
            add_call = [call for call in fake.calls if "add" in call][0]
            self.assertNotIn("--json", add_call)

    def test_installed_plugin_is_skipped(self) -> None:
        # Given the plugin is already installed and enabled.
        with tempfile.TemporaryDirectory() as tmp:
            fake, installed = run_claude_ensure({"plugin list": CLAUDE_PLUGIN_LIST}, Path(tmp))
            # Then nothing beyond the state inspection runs.
            self.assertTrue(installed)
            self.assertEqual(fake.calls, [["claude", "plugin", "list", "--json"]])

    def test_disabled_plugin_is_not_reinstalled(self) -> None:
        # Given the user disabled the installed plugin.
        with tempfile.TemporaryDirectory() as tmp:
            disabled = [{"id": pull.CLAUDE_WAKATIME_PLUGIN_ID, "enabled": False}]
            fake, installed = run_claude_ensure({"plugin list": disabled}, Path(tmp))
            # Then the choice is reported and left alone.
            self.assertTrue(installed)
            self.assertEqual(fake.calls, [["claude", "plugin", "list", "--json"]])

    def test_existing_marketplace_is_reused(self) -> None:
        # Given the marketplace already points at the documented source.
        with tempfile.TemporaryDirectory() as tmp:
            fake, installed = run_claude_ensure(
                {
                    "plugin list": [],
                    "marketplace list": [CLAUDE_MARKETPLACE_ENTRY],
                    "plugin install": {"outcome": "ok"},
                },
                Path(tmp),
            )
            # Then the installer skips marketplace add and installs the plugin.
            self.assertTrue(installed)
            self.assertEqual(len(fake.calls), 3)
            self.assertEqual(
                fake.calls[-1],
                ["claude", "plugin", "install", pull.CLAUDE_WAKATIME_PLUGIN_ID, "--json"],
            )

    def test_shorthand_marketplace_is_recognized(self) -> None:
        # Given a marketplace added earlier by GitHub shorthand instead of URL.
        with tempfile.TemporaryDirectory() as tmp:
            entry = {
                "name": pull.WAKATIME_MARKETPLACE,
                "source": "github",
                "repo": pull.CLAUDE_WAKATIME_MARKETPLACE_REPO,
            }
            fake, installed = run_claude_ensure(
                {
                    "plugin list": [],
                    "marketplace list": [entry],
                    "plugin install": {"outcome": "ok"},
                },
                Path(tmp),
            )
            # Then it is still treated as the documented source.
            self.assertTrue(installed)
            self.assertEqual(len(fake.calls), 3)

    def test_foreign_marketplace_source_is_not_replaced(self) -> None:
        # Given another marketplace already claims the wakatime name.
        with tempfile.TemporaryDirectory() as tmp:
            foreign = {"name": pull.WAKATIME_MARKETPLACE, "source": "git",
                       "url": "https://example.test/other.git"}
            fake, installed = run_claude_ensure(
                {"plugin list": [], "marketplace list": [foreign]},
                Path(tmp),
            )
            # Then the installer stops instead of overwriting the user's source.
            self.assertFalse(installed)
            self.assertEqual(len(fake.calls), 2)

    def test_failed_install_outcome_is_reported(self) -> None:
        # Given Claude Code reports an install outcome other than ok.
        with tempfile.TemporaryDirectory() as tmp:
            _, installed = run_claude_ensure(
                {
                    "plugin list": [],
                    "marketplace list": [CLAUDE_MARKETPLACE_ENTRY],
                    "plugin install": {"outcome": "needs-confirmation"},
                },
                Path(tmp),
            )
            # Then the step fails instead of claiming success.
            self.assertFalse(installed)

    def test_missing_claude_cli_skips_quietly(self) -> None:
        # Given Claude Code is not installed on this machine.
        with tempfile.TemporaryDirectory() as tmp:
            fake = FakeCli({})
            with patch.object(pull.subprocess, "run", fake), \
                    patch.object(pull.shutil, "which", lambda name: None):
                installed = pull.ensure_claude_wakatime_plugin(Path(tmp))
            # Then no Claude Code command is attempted.
            self.assertFalse(installed)
            self.assertEqual(fake.calls, [])


class WakatimePrerequisiteTests(unittest.TestCase):
    def test_prerequisites_are_not_checked_when_both_steps_skip(self) -> None:
        # Given neither agent CLI is available.
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(pull.shutil, "which", lambda name: None), \
                patch.object(pull, "get_wakatime_config_path") as config_path:
            pull.ensure_wakatime_plugins(Path(tmp), Path(tmp))
        # Then the shared WakaTime prerequisites are not reported at all.
        config_path.assert_not_called()

    def test_missing_wakatime_config_is_reported_once(self) -> None:
        # Given both plugins are already installed but the config file is absent.
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "absent.cfg"
            fake = FakeCli({"plugin list": INSTALLED_PLUGIN_LIST})
            fake_claude = FakeCli({"plugin list": CLAUDE_PLUGIN_LIST})

            def run(argv, **kwargs):
                return (fake_claude if argv[0] == "claude" else fake)(argv, **kwargs)

            executables = {"codex": "/c", "claude": "/c", "node": "/n"}
            with patch.object(pull.subprocess, "run", run), \
                    patch.object(pull.shutil, "which", lambda name: executables.get(name)), \
                    patch.object(pull, "get_wakatime_config_path", lambda: missing), \
                    contextlib.redirect_stderr(io.StringIO()) as stderr:
                pull.ensure_wakatime_plugins(Path(tmp), Path(tmp))
        # Then exactly one warning names the missing config file.
        self.assertEqual(stderr.getvalue().count(str(missing)), 1)


if __name__ == "__main__":
    unittest.main()
