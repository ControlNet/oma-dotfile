"""Synthetic TOML lines only; the tomllib-free path must work before Python 3.11."""

from pathlib import Path
import unittest
from unittest.mock import patch

from omadotfile.agents import codex
from omadotfile.core import toml_edit
from support import TestCase


class TomlFallbackTests(TestCase):
    def setUp(self) -> None:
        # Force the fallback even when the running Python ships tomllib.
        patcher = patch.object(toml_edit, "tomllib", None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_multiline_notify_is_replaced_as_one_assignment(self) -> None:
        # Given a multiline notify array containing brackets inside strings and comments.
        lines = [
            'model = "gpt"',
            "notify = [",
            '  "python3", # trailing ] comment',
            "  '/tmp/a]b.py',",
            '  "x\\"]",',
            "]",
            "[profiles.work]",
            'model = "gpt"',
        ]
        # When the notify config is rewritten.
        result = codex.ensure_notify(lines, Path("/codex"))
        # Then only the whole old array is replaced.
        self.assertEqual(result[0], 'model = "gpt"')
        self.assertTrue(result[1].startswith("notify = ["))
        self.assertEqual(result[2:], ["[profiles.work]", 'model = "gpt"'])

    def test_multiline_string_in_array_is_not_split(self) -> None:
        # Given a multiline literal string with a closing bracket on its own line.
        lines = ["notify = ['''", "]", "''']", "[tui]"]
        # When the end of the assignment is located.
        end = toml_edit.find_toml_key_assignment_end_idx(lines, 0, "notify")
        # Then the range covers the whole value.
        self.assertEqual(end, 3)

    def test_single_line_notify_ends_on_same_line(self) -> None:
        # Given a single-line notify assignment.
        lines = ['notify = ["a", "b"] # done', 'model = "gpt"']
        # When the end of the assignment is located.
        end = toml_edit.find_toml_key_assignment_end_idx(lines, 0, "notify")
        # Then only that line belongs to it.
        self.assertEqual(end, 1)

    def test_structure_scan_skips_multiline_strings_and_reads_commented_headers(self) -> None:
        # Given a multiline string holding a header-like line, then a commented header.
        lines = ['x = """', "[fake]", '"""', "[real] # note", "y = 1"]
        # Then only the real header counts, in both lookups.
        self.assertEqual(toml_edit.find_first_toml_section_idx(lines), 3)
        self.assertEqual(toml_edit.replace_toml_section(lines, "real", ["[real]", "y = 2"]),
                         ['x = """', "[fake]", '"""', "[real]", "y = 2"])

    def test_multiline_string_may_end_with_extra_quotes(self) -> None:
        # Given multiline strings ending in four and five quotes (one and two in the content).
        for ending in ('""""', '"""""', "''''", "'''''"):
            quote = ending[0]
            with self.subTest(ending=ending):
                lines = [f"developer_instructions = {quote * 3}Say {quote}done{ending}",
                         "[profiles.work]", 'model = "gpt"']
                result = codex.ensure_notify(lines, Path("/codex"))
                # Then notify is top-level and the later table is untouched.
                self.assertTrue(result[1].startswith("notify = ["), result)
                self.assertEqual(result[2:], lines[1:])

    def test_oauth_comments_only_codex_api_selector(self) -> None:
        # Given top-level selectors with both quote styles and a nested selector.
        lines = [
            "model_provider = 'codex_api' # managed",
            "[profiles.work]",
            'model_provider = "codex_api"',
        ]
        # When OAuth mode disables the managed gateway.
        result = codex.ensure_oauth_provider(lines)
        # Then only the top-level selector is commented out.
        self.assertEqual(result[0], "# model_provider = 'codex_api' # managed")
        self.assertEqual(result[1:], lines[1:])

    def test_oauth_comments_quoted_key_selector(self) -> None:
        lines = ['"model_provider" = "codex_api"', "[tui]"]
        result = codex.ensure_oauth_provider(lines)
        self.assertEqual(result, ['# "model_provider" = "codex_api"', "[tui]"])

    def test_oauth_keeps_other_or_invalid_selectors(self) -> None:
        # Given selectors that are not the managed gateway.
        lines = ['model_provider = "openai"', 'model_provider = "codex_api" "x"']
        # When OAuth mode runs.
        result = codex.ensure_oauth_provider(lines)
        # Then they are left untouched instead of crashing.
        self.assertEqual(result, lines)

    def test_api_mode_restores_commented_selector(self) -> None:
        # Given a selector disabled by a previous OAuth install.
        lines = ['# model_provider = "codex_api"', 'model = "gpt"']
        # When API mode runs.
        result = codex.ensure_api_provider(lines, "https://example.test/v1")
        # Then the selector is restored in place without duplicates.
        self.assertEqual(result[:2], ['model_provider = "codex_api"', 'model = "gpt"'])
        self.assertEqual(sum(line.startswith("model_provider") for line in result), 1)
        self.assertIn('base_url = "https://example.test/v1"', result)


if __name__ == "__main__":
    unittest.main()
