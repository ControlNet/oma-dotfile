"""Synthetic settings in temporary directories; no user configuration is changed."""

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pull", ROOT / "pull.py")
pull = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pull)


class TokscaleAliasesTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.config = self.directory / "tokscale"
        self.config.mkdir()
        self.settings = self.config / "settings.json"
        self.enterContext(patch.object(pull, "NO_BACKUP", False))

    def install(self, repo=ROOT):
        pull.install_tokscale_model_aliases(repo, self.config, "20260908-120000")

    def test_merge_backup_and_idempotence(self):
        original = {
            "colorPalette": "blue", "scanner": {"extraScanPaths": {}},
            "modelAliases": {"local-name": "gpt-5.5", "codex/gpt-5.5": "old-name"},
        }
        self.settings.write_text(json.dumps(original))
        self.install()
        saved = json.loads(self.settings.read_text())
        self.assertEqual(saved["scanner"], original["scanner"])
        self.assertEqual(saved["colorPalette"], "blue")
        self.assertEqual(saved["modelAliases"]["local-name"], "gpt-5.5")
        self.assertEqual(saved["modelAliases"]["codex/gpt-5.5"], "gpt-5.5")
        backup = self.settings.with_suffix(".json.bak-20260908-120000")
        self.assertEqual(json.loads(backup.read_text()), original)
        before = self.settings.stat().st_mtime_ns
        self.install()
        self.assertEqual(self.settings.stat().st_mtime_ns, before)
        self.assertEqual(json.loads(backup.read_text()), original)

    def test_create_settings_and_parent(self):
        self.config = self.directory / "new" / "tokscale"
        self.install()
        saved = json.loads((self.config / "settings.json").read_text())
        self.assertEqual(saved, {"modelAliases": json.loads((ROOT / "tokscale_model_alias.json").read_text())})

    def test_invalid_settings_remain_untouched(self):
        for content in ("{", "[]", '{"modelAliases": null}'):
            with self.subTest(content=content):
                self.settings.write_text(content)
                self.install()
                self.assertEqual(self.settings.read_text(), content)
                self.assertEqual(list(self.config.glob("*.bak-*")), [])

    def test_invalid_or_missing_source_leaves_settings_untouched(self):
        self.settings.write_text('{"colorPalette": "blue"}')
        for content in (None, "[]", '{"alias": null}', '{"alias": " "}'):
            with self.subTest(content=content):
                if content is not None:
                    (self.directory / "tokscale_model_alias.json").write_text(content)
                self.install(self.directory)
                self.assertEqual(self.settings.read_text(), '{"colorPalette": "blue"}')

    def test_no_backup(self):
        self.settings.write_text("{}")
        with patch.object(pull, "NO_BACKUP", True):
            self.install()
        self.assertEqual(list(self.config.glob("*.bak-*")), [])

    def test_platform_paths_and_override(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(Path, "home", return_value=self.directory):
            self.assertEqual(pull.get_tokscale_config_dir(), self.directory / ".config/tokscale")
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.directory / "xdg")}), patch.object(pull.sys, "platform", "linux"):
                self.assertEqual(pull.get_tokscale_config_dir(), self.directory / "xdg/tokscale")
                with patch.object(pull.sys, "platform", "darwin"):
                    self.assertEqual(pull.get_tokscale_config_dir(), self.directory / ".config/tokscale")
            with patch.dict(os.environ, {"APPDATA": str(self.directory / "appdata")}), patch.object(pull.sys, "platform", "win32"):
                self.assertEqual(pull.get_tokscale_config_dir(), self.directory / "appdata/tokscale")
            with patch.dict(os.environ, {"TOKSCALE_CONFIG_DIR": str(self.config)}):
                self.assertEqual(pull.get_tokscale_config_dir(), self.config)

    def test_repository_model_coverage(self):
        aliases = json.loads((ROOT / "tokscale_model_alias.json").read_text())
        models = json.loads((ROOT / "opencode.jsonc").read_text())["provider"]["codex"]["models"]
        for model_id in models:
            for provider in ("openai", "codex", "codex_api", "omp"):
                self.assertEqual(aliases[f"{provider}/{model_id}"], model_id)
        self.assertEqual(aliases["anthropic/claude-opus-4-6"], "claude-opus-4-6")
        self.assertTrue(all("/" not in value for value in aliases.values()))


if __name__ == "__main__":
    unittest.main()
