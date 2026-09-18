"""Mocked Codex CLI calls only; no marketplace is contacted and no user state changes."""

import importlib.util
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


class FakeCodex:
    """Answer codex plugin subcommands from a canned JSON response table."""

    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.calls: list[list[str]] = []
        self.envs: list[dict[str, str]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        self.envs.append(dict(kwargs.get("env") or {}))
        for key, payload in self.responses.items():
            if key in " ".join(argv):
                return subprocess.CompletedProcess(
                    argv, 0, stdout=json.dumps(payload), stderr=""
                )
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="unexpected")


def run_ensure(responses: dict[str, object], codex_dir: Path, has_node: bool = True):
    fake = FakeCodex(responses)
    executables = {"codex": "/usr/bin/codex"}
    if has_node:
        executables["node"] = "/usr/bin/node"
    with patch.object(pull.subprocess, "run", fake), \
            patch.object(pull.shutil, "which", lambda name: executables.get(name)):
        pull.ensure_codex_wakatime_plugin(codex_dir)
    return fake


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
                     pull.WAKATIME_MARKETPLACE_SOURCE, "--json"],
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
            fake = FakeCodex({})
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


if __name__ == "__main__":
    unittest.main()
