"""OMP's config.yml is merged, not replaced: OMP writes to it too. Temporary dirs only."""

import contextlib
import io
from pathlib import Path
import tempfile
import textwrap
import unittest

from omadotfile.agents import omp
from omadotfile.core import yaml_merge
from support import ROOT, make_context

REPO_CONFIG = (ROOT / "omp_config.yml").read_text(encoding="utf-8")


def yaml(text: str) -> str:
    return textwrap.dedent(text).lstrip("\n")


class MergeTests(unittest.TestCase):
    def test_keys_only_in_the_existing_file_are_kept(self):
        existing = yaml("""
            theme:
              dark: old
            dev:
              autoqaConsent: granted""")
        managed = yaml("""
            theme:
              dark: titanium
            """)
        self.assertEqual(yaml_merge.merge(existing, managed), yaml("""
            theme:
              dark: titanium
            dev:
              autoqaConsent: granted
            """))

    def test_simple_mappings_merge_key_by_key(self):
        existing = yaml("""
            tui:
              tight: true
              addedByOmp: 3
            """)
        managed = yaml("""
            tui:
              renderMermaid: true
              tight: false
            """)
        self.assertEqual(yaml_merge.merge(existing, managed), yaml("""
            tui:
              tight: false
              addedByOmp: 3
              renderMermaid: true
            """))

    def test_lists_scalars_and_nested_blocks_come_from_the_repo(self):
        existing = yaml("""
            disabledProviders:
              - azure
              - extra
            symbolPreset: ascii
            nested:
              inner:
                a: 1
            """)
        managed = yaml("""
            disabledProviders:
              - azure
            symbolPreset: unicode
            nested:
              inner:
                b: 2
            """)
        self.assertEqual(yaml_merge.merge(existing, managed), managed)

    def test_existing_order_is_kept_and_new_keys_go_last(self):
        existing = yaml("""
            b: 1
            a: 1
            """)
        managed = yaml("""
            a: 2
            b: 2
            c: 2
            """)
        self.assertEqual(yaml_merge.merge(existing, managed), "b: 2\na: 2\nc: 2\n")

    def test_an_unchanged_file_is_returned_as_it_is(self):
        # OMP writes without a final newline; that alone is no reason to rewrite it.
        existing = yaml("""
            theme:
              dark: titanium
            dev:
              autoqaConsent: granted""")
        managed = "theme:\n  dark: titanium\n"
        self.assertEqual(yaml_merge.merge(existing, managed), existing)

    def test_empty_existing_file_gives_the_repo_file(self):
        self.assertEqual(yaml_merge.merge("", REPO_CONFIG), REPO_CONFIG)

    def test_unsupported_shapes_are_not_merged(self):
        for text in ("{a: 1}\n", "- a\n", "a: |\n  text\n", "---\na: 1\n...\n", "a: 1\n\tb: 2\n"):
            with self.subTest(text=text):
                self.assertIsNone(yaml_merge.blocks(text))
                self.assertIsNone(yaml_merge.merge(text, "a: 2\n"))

    def test_repo_config_is_in_the_supported_shape(self):
        self.assertIsNotNone(yaml_merge.blocks(REPO_CONFIG))

    def test_repo_config_quotes_off(self):
        # OMP writes "off" quoted (YAML 1.1 reads bare off as false); bare off would
        # differ from OMP's own copy on every install.
        self.assertNotRegex(REPO_CONFIG, r":\s*off\s*$")
        self.assertIn('notify: "off"', REPO_CONFIG)


class OmpConfigInstallTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.agent_dir = self.home / ".omp" / "agent"
        self.agent_dir.mkdir(parents=True)
        self.config = self.agent_dir / "config.yml"

    def install(self, oauth=False, stamp="20261107-120000"):
        ctx = make_context(self.home, oauth=oauth, stamp=stamp,
                           dirs={"omp": self.agent_dir})
        spec = next(spec for spec in omp.Omp.files if spec.dst == "config.yml")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            omp.Omp().install_file(ctx, spec, self.agent_dir)
        return ctx, err.getvalue()

    def test_fresh_install_writes_the_repo_config(self):
        self.install()
        self.assertEqual(self.config.read_text(), REPO_CONFIG)

    def test_omp_written_keys_survive_and_rerun_writes_nothing(self):
        self.config.write_text(REPO_CONFIG.rstrip("\n") + "\ndev:\n  autoqaConsent: granted")
        before = self.config.read_text()

        ctx, _ = self.install()

        self.assertEqual(self.config.read_text(), before)
        self.assertEqual(ctx.files.changed, [])
        self.assertEqual(list(self.agent_dir.glob("*.bak-*")), [])

    def test_changed_managed_key_is_restored_with_a_backup(self):
        edited = REPO_CONFIG.replace("dark: titanium", "dark: other") + "dev:\n  autoqaConsent: granted\n"
        self.config.write_text(edited)

        self.install()

        self.assertEqual(self.config.read_text(), REPO_CONFIG + "dev:\n  autoqaConsent: granted\n")
        backup = self.agent_dir / "config.yml.bak-20261107-120000"
        self.assertEqual(backup.read_text(), edited)

    def test_oauth_rewrites_models_then_merges(self):
        self.config.write_text(REPO_CONFIG + "dev:\n  autoqaConsent: granted\n")

        self.install(oauth=True)

        content = self.config.read_text()
        self.assertNotIn("codex_api/", content)
        self.assertIn("default: openai-codex/", content)
        self.assertTrue(content.endswith("dev:\n  autoqaConsent: granted\n"))

    def test_unmergeable_config_is_replaced_with_a_backup_and_a_warning(self):
        self.config.write_text("{theme: {dark: other}}\n")

        _, err = self.install()

        self.assertEqual(self.config.read_text(), REPO_CONFIG)
        self.assertIn("could not be merged", err)
        backup = self.agent_dir / "config.yml.bak-20261107-120000"
        self.assertEqual(backup.read_text(), "{theme: {dark: other}}\n")


if __name__ == "__main__":
    unittest.main()
