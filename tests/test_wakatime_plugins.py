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
        # Commands run by absolute path; calls keep the bare name, executables the path.
        self.calls: list[list[str]] = []
        self.executables: list[str] = []
        self.envs: list[dict[str, str]] = []

    def __call__(self, argv, **kwargs):
        self.executables.append(argv[0])
        self.calls.append([Path(argv[0]).name, *argv[1:]])
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
            patch.object(pull.shutil, "which", lambda name, path=None: executables.get(name)):
        pull.ensure_codex_wakatime_plugin(codex_dir)
    return fake


def run_claude_ensure(responses: dict[str, object], claude_config_dir: Path):
    fake = FakeCli(responses)
    executables = {"claude": "/usr/bin/claude", "node": "/usr/bin/node"}
    with patch.object(pull.subprocess, "run", fake), \
            patch.object(pull.shutil, "which", lambda name, path=None: executables.get(name)):
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
                    patch.object(pull.shutil, "which", lambda name, path=None: None):
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
                    patch.object(pull.shutil, "which", lambda name, path=None: None):
                installed = pull.ensure_claude_wakatime_plugin(Path(tmp))
            # Then no Claude Code command is attempted.
            self.assertFalse(installed)
            self.assertEqual(fake.calls, [])


class AgentCliLookupTests(unittest.TestCase):
    def test_cli_only_in_extra_bin_dir_is_used_by_path(self) -> None:
        # Given codex installed only in an extra bin dir that a piped install's PATH lacks.
        extra = "/home/me/.bun/bin/codex"
        fake = FakeCli({"plugin list": INSTALLED_PLUGIN_LIST})
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(pull.subprocess, "run", fake), \
                patch.object(pull.shutil, "which",
                             lambda name, path=None: extra if path and name == "codex" else None):
            # When the WakaTime step runs.
            installed = pull.ensure_codex_wakatime_plugin(Path(tmp))
        # Then it finds the CLI there, calls it by path, and puts its dir on PATH for its runtime.
        self.assertTrue(installed)
        self.assertEqual(fake.executables[0], extra)
        self.assertEqual(fake.envs[0]["PATH"].split(pull.os.pathsep)[0], "/home/me/.bun/bin")


class WakatimePrerequisiteTests(unittest.TestCase):
    def test_prerequisites_are_not_checked_when_both_steps_skip(self) -> None:
        # Given neither agent CLI is available.
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(pull.shutil, "which", lambda name, path=None: None), \
                patch.object(pull, "get_wakatime_config_path") as config_path:
            pull.ensure_wakatime_plugins(Path(tmp), Path(tmp))
        # Then the shared WakaTime prerequisites are not reported at all.
        config_path.assert_not_called()


# Test-only fake credentials; they never reach a WakaTime server.
FAKE_KEY = "test-only-fake-wakatime-key"
FAKE_URL = "https://wakapi.example.invalid/api"
WAKATIME_ENV_NAMES = ("WAKATIME_HOME", "WAKATIME_API_KEY", "WAKATIME_API_URL")


class WakatimeConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.cfg = self.tmp / ".wakatime.cfg"
        self.enterContext(patch.object(pull, "get_wakatime_config_path", lambda: self.cfg))
        # Backups are on, to show that the cfg is still written without one.
        self.enterContext(patch.object(pull, "NO_BACKUP", False))
        # The developer's own WakaTime variables must not leak into these tests.
        self.enterContext(patch.dict(pull.os.environ))
        for name in WAKATIME_ENV_NAMES:
            pull.os.environ.pop(name, None)

    def ensure(self, **env: str) -> tuple[str, str]:
        with patch.dict(pull.os.environ, env), \
                contextlib.redirect_stdout(io.StringIO()) as out, \
                contextlib.redirect_stderr(io.StringIO()) as err:
            pull.ensure_wakatime_config()
        return out.getvalue(), err.getvalue()

    def test_env_creates_private_config(self) -> None:
        # Given no config file and both variables set.
        out, err = self.ensure(WAKATIME_API_URL=FAKE_URL, WAKATIME_API_KEY=FAKE_KEY)
        # Then a [settings] section holds both values and only the owner can read it.
        self.assertEqual(self.cfg.read_text(encoding="utf-8"),
                         f"[settings]\napi_url = {FAKE_URL}\napi_key = {FAKE_KEY}\n")
        self.assertEqual(self.cfg.stat().st_mode & 0o777, 0o600)
        # And the key is never printed.
        self.assertNotIn(FAKE_KEY, out + err)

    def test_env_replaces_only_managed_keys(self) -> None:
        # Given a config with other settings, comments, sections and the legacy apikey alias.
        self.cfg.write_text(
            "; personal settings\n"
            "[settings]\n"
            "debug = true\n"
            "apikey = old-key\n"
            "api_url = https://old.example.invalid/api\n"
            "proxy = http://127.0.0.1:3128\n"
            "\n"
            "[api_urls]\n"
            ".* = https://other.example.invalid|other-key\n",
            encoding="utf-8",
        )
        self.cfg.chmod(0o644)
        self.ensure(WAKATIME_API_URL=FAKE_URL, WAKATIME_API_KEY=FAKE_KEY)
        # Then the two keys change in place and everything else survives.
        self.assertEqual(
            self.cfg.read_text(encoding="utf-8"),
            "; personal settings\n"
            "[settings]\n"
            "debug = true\n"
            f"api_key = {FAKE_KEY}\n"
            f"api_url = {FAKE_URL}\n"
            "proxy = http://127.0.0.1:3128\n"
            "\n"
            "[api_urls]\n"
            ".* = https://other.example.invalid|other-key\n",
        )
        # And a readable file becomes owner-only once it holds the key, with no backup.
        self.assertEqual(self.cfg.stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(self.tmp.glob(".wakatime.cfg.bak-*")), [])

    def test_key_only_leaves_api_url_alone(self) -> None:
        # Given a config whose section has no api_url and ends before another section.
        self.cfg.write_text("[settings]\ndebug = false\n\n[internal]\nx = 1\n", encoding="utf-8")
        self.ensure(WAKATIME_API_KEY=FAKE_KEY)
        # Then only api_key is added, at the end of [settings].
        self.assertEqual(self.cfg.read_text(encoding="utf-8"),
                         f"[settings]\ndebug = false\napi_key = {FAKE_KEY}\n\n[internal]\nx = 1\n")

    def test_url_only_keeps_file_mode(self) -> None:
        # Given a shared-readable config and no key to write.
        self.cfg.write_text("[settings]\ndebug = true\n", encoding="utf-8")
        self.cfg.chmod(0o644)
        self.ensure(WAKATIME_API_URL=FAKE_URL)
        # Then its mode is left as the user set it.
        self.assertEqual(self.cfg.stat().st_mode & 0o777, 0o644)

    def test_missing_settings_section_is_appended(self) -> None:
        self.cfg.write_text("[git]\nsubmodules_disabled = true\n", encoding="utf-8")
        self.ensure(WAKATIME_API_URL=FAKE_URL)
        self.assertEqual(self.cfg.read_text(encoding="utf-8"),
                         f"[git]\nsubmodules_disabled = true\n\n[settings]\napi_url = {FAKE_URL}\n")

    def test_unchanged_config_is_not_rewritten(self) -> None:
        # Given a config that already matches the environment.
        self.ensure(WAKATIME_API_URL=FAKE_URL, WAKATIME_API_KEY=FAKE_KEY)
        with patch.object(pull.os, "open") as open_file:
            out, _ = self.ensure(WAKATIME_API_URL=FAKE_URL, WAKATIME_API_KEY=FAKE_KEY)
        # Then the file is not opened for writing.
        open_file.assert_not_called()
        self.assertIn("skip", out)

    def test_unchanged_config_with_key_is_still_made_private(self) -> None:
        # Given a shared-readable config an older installer already wrote the key into.
        self.ensure(WAKATIME_API_URL=FAKE_URL, WAKATIME_API_KEY=FAKE_KEY)
        self.cfg.chmod(0o644)
        self.ensure(WAKATIME_API_URL=FAKE_URL, WAKATIME_API_KEY=FAKE_KEY)
        # Then rerunning makes it owner-only even though its content does not change.
        self.assertEqual(self.cfg.stat().st_mode & 0o777, 0o600)

    def test_line_break_in_value_is_rejected(self) -> None:
        # Given a value that would inject another INI line.
        _, err = self.ensure(WAKATIME_API_URL=f"{FAKE_URL}\ndebug = true")
        # Then nothing is written and the variable is named.
        self.assertFalse(self.cfg.exists())
        self.assertIn("WAKATIME_API_URL", err)

    def test_without_env_nothing_is_created(self) -> None:
        # Given neither variable set and no config file.
        _, err = self.ensure()
        # Then no file appears and exactly one warning names the missing config.
        self.assertFalse(self.cfg.exists())
        self.assertEqual(err.count(str(self.cfg)), 1)

    def test_existing_config_without_env_is_left_quietly(self) -> None:
        self.cfg.write_text("[settings]\napi_key = kept\n", encoding="utf-8")
        _, err = self.ensure()
        self.assertEqual(self.cfg.read_text(encoding="utf-8"), "[settings]\napi_key = kept\n")
        self.assertEqual(err, "")


if __name__ == "__main__":
    unittest.main()
