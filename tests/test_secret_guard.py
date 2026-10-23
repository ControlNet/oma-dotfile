import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCANNER = Path(__file__).resolve().parents[1] / "skills" / "secret-guard" / "scripts" / "scan_secrets.py"
# Test-only fake credential; it matches the "Password Assignment" pattern and nothing real.
FAKE_SECRET_LINE = 'password = "test-only-fake-password"\n'


class StagedScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.git("init", "-q")

    def git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True)

    def stage(self, name: str, content: str) -> Path:
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self.git("add", "--", name)
        return path

    def scan_staged(self, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCANNER), "staged"],
            cwd=cwd or self.repo, capture_output=True, text=True, timeout=60,
            env={**os.environ, "TERM": "dumb"},
        )

    def test_secret_staged_then_cleaned_in_working_tree_is_found(self) -> None:
        # Given a secret staged, then removed from the working copy without restaging.
        path = self.stage("config.txt", FAKE_SECRET_LINE)
        path.write_text("password = None\n", encoding="utf-8")
        # Then the scan reports what will be committed.
        result = self.scan_staged()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("Password Assignment", result.stdout)

    def test_secret_staged_then_deleted_from_working_tree_is_found(self) -> None:
        self.stage("config.txt", FAKE_SECRET_LINE).unlink()
        result = self.scan_staged()
        self.assertEqual(result.returncode, 1, result.stdout)

    def test_secret_cleaned_before_staging_is_not_reported(self) -> None:
        # Given a working copy that still holds the secret but an index that does not.
        path = self.stage("config.txt", "password = None\n")
        path.write_text(FAKE_SECRET_LINE, encoding="utf-8")
        result = self.scan_staged()
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_scan_from_a_subdirectory_and_unusual_names(self) -> None:
        # Given secrets in a nested file and in a name Git would quote without -z.
        self.stage("pkg/settings.txt", FAKE_SECRET_LINE)
        self.stage("café notes.txt", FAKE_SECRET_LINE)
        # When scanning from a subdirectory.
        result = self.scan_staged(cwd=self.repo / "pkg")
        # Then both files are read from the index.
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("pkg/settings.txt", result.stdout)
        self.assertIn("café notes.txt", result.stdout)

    def test_staged_binary_blob_is_skipped(self) -> None:
        self.stage("blob.bin", "\x00" + FAKE_SECRET_LINE)
        result = self.scan_staged()
        self.assertEqual(result.returncode, 0, result.stdout)


if __name__ == "__main__":
    unittest.main()
