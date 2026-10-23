"""Synthetic TOML and URLs in temporary directories; no user config is changed."""

import importlib.util
import os
from pathlib import Path, PureWindowsPath
import tempfile
import tomllib
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pull", ROOT / "pull.py")
assert SPEC is not None and SPEC.loader is not None
pull = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pull)


class CodexProviderConfigTests(unittest.TestCase):
    def test_existing_provider_restores_api_selection(self) -> None:
        for selection in (
            "",
            '# model_provider = "codex_api"\n',
            'model_provider = "openai"\n',
            'model_provider = "codex_api"\n',
        ):
            with self.subTest(selection=selection), tempfile.TemporaryDirectory() as tmp:
                # Given an existing provider, possibly disabled by the user.
                directory = Path(tmp)
                config = directory / "config.toml"
                original = (
                    selection
                    + '[model_providers.codex_api]\nname = "codex_api"\n'
                    + '[profiles.work]\nmodel_provider = "codex_api"\n'
                )
                config.write_text(original, encoding="utf-8")
                with patch.dict(os.environ, {"CODEX_BASE_URL": "https://example.test/v1"}):
                    # When the installer updates the actual file twice.
                    pull.ensure_codex_config(directory, "provider-test")
                    first = config.read_text(encoding="utf-8")
                    pull.ensure_codex_config(directory, "provider-test")
                # Then API routing is restored and nested settings survive.
                saved = tomllib.loads(first)
                self.assertEqual(saved["model_provider"], "codex_api")
                self.assertEqual(saved["profiles"]["work"]["model_provider"], "codex_api")
                self.assertEqual(saved["model_providers"]["codex_api"]["base_url"], "https://example.test/v1")
                self.assertIn("notify", saved)
                self.assertEqual(config.read_text(encoding="utf-8"), first)

    def test_first_install_selects_provider(self) -> None:
        for original in ("", 'model_provider = "openai"\n'):
            with self.subTest(original=original):
                # Given no existing codex_api provider section.
                with patch.dict(os.environ, {"CODEX_BASE_URL": "https://example.test/v1"}):
                    # When provider configuration is installed.
                    lines = pull.ensure_codex_api_provider_config(original.splitlines())
                # Then the existing first-install behavior is preserved.
                saved = tomllib.loads("\n".join(lines))
                self.assertEqual(saved["model_provider"], "codex_api")
                self.assertEqual(saved["model_providers"]["codex_api"]["wire_api"], "responses")
                self.assertEqual(saved["model_providers"]["codex_api"]["env_key"], "CODEX_API_TOKEN")

    def test_empty_base_url_preserves_configuration(self) -> None:
        # Given a disabled provider and no usable URL.
        lines = ['# model_provider = "codex_api"', '[model_providers.codex_api]']
        with patch.dict(os.environ, {"CODEX_BASE_URL": " "}):
            # When provider configuration is requested.
            result = pull.ensure_codex_api_provider_config(lines)
        # Then configuration is unchanged.
        self.assertEqual(result, lines)


class CodexNotifyPathTests(unittest.TestCase):
    def render_notify(self, python_bin: str, codex_dir: str) -> list:
        with patch.object(pull.sys, "executable", python_bin):
            lines = pull.ensure_codex_notify_config_lines([], PureWindowsPath(codex_dir)
                                                     if "\\" in codex_dir else Path(codex_dir))
        return tomllib.loads("\n".join(lines))["notify"]

    def test_windows_paths_round_trip(self) -> None:
        # Given the paths a PowerShell install produces; "\P" is not a valid TOML escape.
        notify = self.render_notify(r"C:\Python312\python.exe", r"C:\Users\me\.codex")
        # Then the written array parses back to the same paths.
        self.assertEqual(notify, [r"C:\Python312\python.exe", r"C:\Users\me\.codex\codex-gotify-notify.py"])

    def test_quotes_in_paths_round_trip(self) -> None:
        notify = self.render_notify('/opt/py "3"/bin/python', "/home/me/.codex")
        self.assertEqual(notify, ['/opt/py "3"/bin/python', "/home/me/.codex/codex-gotify-notify.py"])


if __name__ == "__main__":
    unittest.main()
