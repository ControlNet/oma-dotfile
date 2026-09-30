"""Synthetic TOML lines only; the tomllib-free path must work before Python 3.11."""

import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pull", ROOT / "pull.py")
assert SPEC is not None and SPEC.loader is not None
pull = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pull)


class TomlFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        # Force the fallback even when the running Python ships tomllib.
        patcher = patch.object(pull, "tomllib", None)
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
        result = pull.ensure_codex_notify_config_lines(lines, Path("/codex"))
        # Then only the whole old array is replaced.
        self.assertEqual(result[0], 'model = "gpt"')
        self.assertTrue(result[1].startswith("notify = ["))
        self.assertEqual(result[2:], ["[profiles.work]", 'model = "gpt"'])

    def test_multiline_string_in_array_is_not_split(self) -> None:
        # Given a multiline literal string with a closing bracket on its own line.
        lines = ["notify = ['''", "]", "''']", "[tui]"]
        # When the end of the assignment is located.
        end = pull.find_toml_key_assignment_end_idx(lines, 0, "notify")
        # Then the range covers the whole value.
        self.assertEqual(end, 3)

    def test_single_line_notify_ends_on_same_line(self) -> None:
        # Given a single-line notify assignment.
        lines = ['notify = ["a", "b"] # done', 'model = "gpt"']
        # When the end of the assignment is located.
        end = pull.find_toml_key_assignment_end_idx(lines, 0, "notify")
        # Then only that line belongs to it.
        self.assertEqual(end, 1)

    def test_oauth_comments_only_codex_api_selector(self) -> None:
        # Given top-level selectors with both quote styles and a nested selector.
        lines = [
            "model_provider = 'codex_api' # managed",
            "[profiles.work]",
            'model_provider = "codex_api"',
        ]
        # When OAuth mode disables the managed gateway.
        result = pull.ensure_codex_oauth_provider_config(lines)
        # Then only the top-level selector is commented out.
        self.assertEqual(result[0], "# model_provider = 'codex_api' # managed")
        self.assertEqual(result[1:], lines[1:])

    def test_oauth_keeps_other_or_invalid_selectors(self) -> None:
        # Given selectors that are not the managed gateway.
        lines = ['model_provider = "openai"', 'model_provider = "codex_api" "x"']
        # When OAuth mode runs.
        result = pull.ensure_codex_oauth_provider_config(lines)
        # Then they are left untouched instead of crashing.
        self.assertEqual(result, lines)

    def test_api_mode_restores_commented_selector(self) -> None:
        # Given a selector disabled by a previous OAuth install.
        lines = ['# model_provider = "codex_api"', 'model = "gpt"']
        with patch.dict(os.environ, {"CODEX_BASE_URL": "https://example.test/v1"}):
            # When API mode runs.
            result = pull.ensure_codex_api_provider_config(lines)
        # Then the selector is restored in place without duplicates.
        self.assertEqual(result[:2], ['model_provider = "codex_api"', 'model = "gpt"'])
        self.assertEqual(sum(line.startswith("model_provider") for line in result), 1)
        self.assertIn('base_url = "https://example.test/v1"', result)


if __name__ == "__main__":
    unittest.main()
