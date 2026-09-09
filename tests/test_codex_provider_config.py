"""Synthetic TOML and URLs in temporary directories; no user config is changed."""

import importlib.util
import os
from pathlib import Path
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
    def test_existing_provider_preserves_top_level_choice(self) -> None:
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
                # Then the choice, comments, and nested settings survive.
                saved = tomllib.loads(first)
                self.assertEqual(saved.get("model_provider"), tomllib.loads(original).get("model_provider"))
                self.assertTrue(first.startswith(selection))
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

    def test_empty_base_url_preserves_configuration(self) -> None:
        # Given a disabled provider and no usable URL.
        lines = ['# model_provider = "codex_api"', '[model_providers.codex_api]']
        with patch.dict(os.environ, {"CODEX_BASE_URL": " "}):
            # When provider configuration is requested.
            result = pull.ensure_codex_api_provider_config(lines)
        # Then configuration is unchanged.
        self.assertEqual(result, lines)


if __name__ == "__main__":
    unittest.main()
