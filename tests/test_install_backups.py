"""Backup policy: back up user-editable config only when it changes; never back up plugin code."""

import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SPEC = importlib.util.spec_from_file_location("pull_backup_policy", ROOT / "pull.py")
pull = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pull)

STAMP = "20261007-120000"


class BackupPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(pull, "NO_BACKUP", False))
        self.src = self.tmp / "src.txt"
        self.dst = self.tmp / "out" / "dst.txt"
        self.dst.parent.mkdir()

    def backups(self, path: Path) -> list[Path]:
        return sorted(path.parent.glob(f"{path.name}.bak-*"))

    def test_identical_config_is_neither_rewritten_nor_backed_up(self):
        _ = self.src.write_text("same\n", encoding="utf-8")
        _ = self.dst.write_text("same\n", encoding="utf-8")
        os.utime(self.dst, ns=(1_000_000_000, 1_000_000_000))

        pull.backup_and_install(self.src, self.dst, STAMP)

        self.assertEqual(self.backups(self.dst), [])
        self.assertEqual(self.dst.stat().st_mtime_ns, 1_000_000_000)

    def test_changed_config_is_backed_up_before_replacing(self):
        _ = self.src.write_text("new\n", encoding="utf-8")
        _ = self.dst.write_text("local edit\n", encoding="utf-8")

        pull.backup_and_install(self.src, self.dst, STAMP)

        self.assertEqual(self.dst.read_text(encoding="utf-8"), "new\n")
        self.assertEqual([p.read_text(encoding="utf-8") for p in self.backups(self.dst)],
                         ["local edit\n"])

    def test_managed_plugin_file_is_replaced_without_backup(self):
        _ = self.src.write_text("plugin v2\n", encoding="utf-8")
        _ = self.dst.write_text("plugin v1\n", encoding="utf-8")

        pull.install_managed_file(self.src, self.dst)

        self.assertEqual(self.dst.read_text(encoding="utf-8"), "plugin v2\n")
        self.assertEqual(self.backups(self.dst), [])

    def test_managed_plugin_file_creates_parent_and_skips_identical_copy(self):
        _ = self.src.write_text("plugin\n", encoding="utf-8")
        dst = self.tmp / "new" / "extensions" / "plugin.js"

        pull.install_managed_file(self.src, dst)
        self.assertEqual(dst.read_text(encoding="utf-8"), "plugin\n")

        os.utime(dst, ns=(1_000_000_000, 1_000_000_000))
        pull.install_managed_file(self.src, dst)
        self.assertEqual(dst.stat().st_mtime_ns, 1_000_000_000)

    def test_rerendered_omp_models_are_not_backed_up_again(self):
        dst = self.tmp / "omp" / "models.yml"
        with patch.dict(os.environ, {"CODEX_BASE_URL": "https://example.invalid/v1"}):
            pull.backup_and_install_omp_models(ROOT / "omp_models.yaml", dst, STAMP)
            pull.backup_and_install_omp_models(ROOT / "omp_models.yaml", dst, "20261007-120001")

        self.assertTrue(dst.is_file())
        self.assertEqual(self.backups(dst), [])


if __name__ == "__main__":
    unittest.main()
