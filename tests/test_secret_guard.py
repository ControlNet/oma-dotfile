import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from support import TestCase


SCANNER = Path(__file__).resolve().parents[1] / "skills" / "secret-guard" / "scripts" / "scan_secrets.py"
# Test-only fake credential; it matches the "Password Assignment" pattern and nothing real.
FAKE_SECRET_LINE = 'password = "test-only-fake-password"\n'


class StagedScanTests(TestCase):
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


def fake(prefix: str, body: str, repeat: int) -> str:
    """A test-only, non-functional token of a provider's shape, assembled at run time so no
    token-shaped literal sits in the repo (GitHub push protection rejects those)."""
    return prefix + body * repeat


class ContentPatternTests(TestCase):
    """Lines a scan must flag or pass; all values are fake and assembled at run time."""

    def labels(self, text: str) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "sample.txt").write_text(text, encoding="utf-8")
            result = subprocess.run([sys.executable, str(SCANNER), "path", tmp], capture_output=True,
                                    text=True, timeout=60, env={**os.environ, "TERM": "dumb"})
        return result.stdout

    def test_assignments_are_found_in_any_case_and_without_quotes(self) -> None:
        value = fake("", "Zq7x", 6)
        for line in (f'OPENAI_API_KEY = "{value}"', f"export GOTIFY_TOKEN={value}",
                     f"api_key: {value}", f"[settings]\napi_key = {value}", f'DB_PASSWORD="{value}"'):
            with self.subTest(line=line):
                self.assertRegex(self.labels(line + "\n"), r"\[(Secret|Password) Assignment\]")

    def test_provider_tokens_are_found(self) -> None:
        for label, token in (
            ("Notion Token", fake("ntn" + "_", "Ab3d", 12)),
            ("Hugging Face Token", fake("hf" + "_", "Ab3d", 9)),
            ("WakaTime API Key", "waka" + "_" + "0a1b2c3d-0a1b-4c5d-8e9f-0a1b2c3d4e5f"),
            ("OpenAI API Key (service account)", fake("sk" + "-svcacct-", "Ab3d", 12)),
        ):
            with self.subTest(label=label):
                self.assertIn(f"[{label}]", self.labels(f"value {token}\n"))

    def test_output_survives_a_legacy_code_page(self) -> None:
        # Windows encodes piped output as cp1252, which has no ▸ or ✓.
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "sample.txt").write_text(FAKE_SECRET_LINE, encoding="utf-8")
            result = subprocess.run([sys.executable, str(SCANNER), "path", tmp], capture_output=True,
                                    timeout=60, env={**os.environ, "TERM": "dumb", "PYTHONIOENCODING": "cp1252"})
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(b"[Password Assignment]", result.stdout)

    def test_names_references_and_counts_are_not_secrets(self) -> None:
        for line in ("password = None", "max_tokens: 128000000000000000", "api_key = settings.API_KEY_NAME",
                     'token = "${GITHUB_TOKEN}"', "token_count = 1234567890123456",
                     "uuid " + fake("ASK", "0a1b2c3d", 4)):
            with self.subTest(line=line):
                self.assertIn("No secrets detected", self.labels(line + "\n"))


if __name__ == "__main__":
    unittest.main()
