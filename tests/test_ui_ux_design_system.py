import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "ui-ux-pro-max" / "scripts" / "design_system.py"
SPEC = importlib.util.spec_from_file_location("ui_ux_design_system", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
design_system = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(design_system)


class PersistTests(unittest.TestCase):
    def setUp(self) -> None:
        self.out = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.master = self.out / "design-system" / "acme" / "MASTER.md"

    def generate(self, query: str, page: str | None = None) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            design_system.generate_design_system(
                query, "Acme", persist=True, page=page, output_dir=str(self.out))

    def test_page_override_keeps_existing_master(self) -> None:
        # Given a project Master the user has edited.
        self.generate("luxury beauty spa wellness")
        edited = self.master.read_text(encoding="utf-8") + "\n<!-- hand-tuned -->\n"
        self.master.write_text(edited, encoding="utf-8")
        # When a page override is generated from a different query.
        self.generate("fintech analytics dashboard", page="Dashboard")
        # Then the Master is untouched and the page file is written.
        self.assertEqual(self.master.read_text(encoding="utf-8"), edited)
        self.assertTrue((self.master.parent / "pages" / "dashboard.md").is_file())

    def test_page_override_creates_missing_master(self) -> None:
        self.generate("fintech analytics dashboard", page="Dashboard")
        self.assertTrue(self.master.is_file())

    def test_project_run_without_page_rewrites_master(self) -> None:
        # Given an edited Master, a project-level run regenerates it as before.
        self.generate("luxury beauty spa wellness")
        self.master.write_text("old\n", encoding="utf-8")
        self.generate("luxury beauty spa wellness")
        self.assertNotEqual(self.master.read_text(encoding="utf-8"), "old\n")


if __name__ == "__main__":
    unittest.main()
