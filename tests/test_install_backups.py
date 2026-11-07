"""Backup policy: back up user-editable config only when it changes; never back up plugin code."""

import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest

from omadotfile.agents import omp
from omadotfile.core.files import Files
from support import ROOT, TestCase, make_context

# Later than the older backup a test plants, so pruning has a newest backup to keep.
STAMP = "20261007-120000"


class BackupPolicyTests(TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.files = Files(STAMP, backup=True, keep=1)
        self.src = self.tmp / "src.txt"
        self.dst = self.tmp / "out" / "dst.txt"
        self.dst.parent.mkdir()

    def backups(self, path: Path) -> list[Path]:
        return sorted(path.parent.glob(f"{path.name}.bak-*"))

    def test_identical_config_is_neither_rewritten_nor_backed_up(self):
        _ = self.src.write_text("same\n", encoding="utf-8")
        _ = self.dst.write_text("same\n", encoding="utf-8")
        os.utime(self.dst, ns=(1_000_000_000, 1_000_000_000))

        self.files.copy(self.src, self.dst)

        self.assertEqual(self.backups(self.dst), [])
        self.assertEqual(self.dst.stat().st_mtime_ns, 1_000_000_000)

    def test_changed_config_is_backed_up_before_replacing(self):
        _ = self.src.write_text("new\n", encoding="utf-8")
        _ = self.dst.write_text("local edit\n", encoding="utf-8")

        self.files.copy(self.src, self.dst)

        self.assertEqual(self.dst.read_text(encoding="utf-8"), "new\n")
        self.assertEqual([p.read_text(encoding="utf-8") for p in self.backups(self.dst)],
                         ["local edit\n"])

    def test_pruning_keeps_the_backup_just_taken(self):
        # Given an older backup, and a config restored from elsewhere with an even older
        # mtime; copy2 gives its backup that old mtime too.
        old_backup = self.dst.with_name(f"{self.dst.name}.bak-20261001-000000")
        _ = old_backup.write_text("older backup\n", encoding="utf-8")
        _ = self.src.write_text("new\n", encoding="utf-8")
        _ = self.dst.write_text("restored config\n", encoding="utf-8")
        os.utime(self.dst, ns=(1_000_000_000, 1_000_000_000))

        self.files.copy(self.src, self.dst)

        # Then the kept backup is the config this run replaced, not the older one.
        self.assertEqual([p.read_text(encoding="utf-8") for p in self.backups(self.dst)],
                         ["restored config\n"])

    def test_managed_plugin_file_is_replaced_without_backup(self):
        _ = self.src.write_text("plugin v2\n", encoding="utf-8")
        _ = self.dst.write_text("plugin v1\n", encoding="utf-8")

        self.files.copy(self.src, self.dst, backup=False)

        self.assertEqual(self.dst.read_text(encoding="utf-8"), "plugin v2\n")
        self.assertEqual(self.backups(self.dst), [])

    def test_managed_plugin_file_creates_parent_and_skips_identical_copy(self):
        _ = self.src.write_text("plugin\n", encoding="utf-8")
        dst = self.tmp / "new" / "extensions" / "plugin.js"

        self.files.copy(self.src, dst, backup=False)
        self.assertEqual(dst.read_text(encoding="utf-8"), "plugin\n")

        os.utime(dst, ns=(1_000_000_000, 1_000_000_000))
        self.files.copy(self.src, dst, backup=False)
        self.assertEqual(dst.stat().st_mtime_ns, 1_000_000_000)

    def test_rerendered_omp_models_are_not_backed_up_again(self):
        agent_dir = self.tmp / "omp"
        dst = agent_dir / "models.yml"
        env = {"CODEX_BASE_URL": "https://example.invalid/v1"}
        with contextlib.redirect_stdout(io.StringIO()):
            for stamp in (STAMP, "20261007-120001"):
                omp.install_models(make_context(self.tmp, repo=ROOT, env=env, stamp=stamp), agent_dir)

        self.assertTrue(dst.is_file())
        self.assertEqual(self.backups(dst), [])


if __name__ == "__main__":
    unittest.main()
