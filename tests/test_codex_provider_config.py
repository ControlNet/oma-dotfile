"""Synthetic TOML and URLs in temporary directories; no user config is changed."""

import contextlib
import io
from pathlib import Path, PureWindowsPath
import tempfile
import unittest
from unittest.mock import patch

from omadotfile.agents import codex
from omadotfile.core import toml_edit
from support import TestCase, make_context, requires_tomllib, tomllib

GATEWAY_ENV = {"CODEX_BASE_URL": "https://example.test/v1"}


class CodexProviderConfigTests(TestCase):
    @requires_tomllib
    def test_existing_provider_restores_api_selection(self) -> None:
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
                ctx = make_context(directory, env=GATEWAY_ENV, stamp="provider-test")
                # When the installer updates the actual file twice.
                codex.ensure_config(ctx, directory)
                first = config.read_text(encoding="utf-8")
                codex.ensure_config(ctx, directory)
                # Then API routing is restored and nested settings survive.
                saved = tomllib.loads(first)
                self.assertEqual(saved["model_provider"], "codex_api")
                self.assertEqual(saved["profiles"]["work"]["model_provider"], "codex_api")
                self.assertEqual(saved["model_providers"]["codex_api"]["base_url"], "https://example.test/v1")
                self.assertIn("notify", saved)
                self.assertEqual(config.read_text(encoding="utf-8"), first)

    @requires_tomllib
    def test_first_install_selects_provider(self) -> None:
        for original in ("", 'model_provider = "openai"\n'):
            with self.subTest(original=original):
                # Given no existing codex_api provider section.
                # When provider configuration is installed.
                lines = codex.ensure_api_provider(original.splitlines(), "https://example.test/v1")
                # Then the existing first-install behavior is preserved.
                saved = tomllib.loads("\n".join(lines))
                self.assertEqual(saved["model_provider"], "codex_api")
                self.assertEqual(saved["model_providers"]["codex_api"]["wire_api"], "responses")
                self.assertEqual(saved["model_providers"]["codex_api"]["env_key"], "CODEX_API_TOKEN")

    def test_empty_base_url_preserves_configuration(self) -> None:
        # Given a disabled provider and no usable URL.
        lines = ['# model_provider = "codex_api"', '[model_providers.codex_api]']
        # When provider configuration is requested (ensure_config strips CODEX_BASE_URL).
        with contextlib.redirect_stderr(io.StringIO()):
            result = codex.ensure_api_provider(lines, " ".strip())
        # Then configuration is unchanged.
        self.assertEqual(result, lines)


class TomlStructureTests(TestCase):
    def provider_update(self, content: str) -> dict:
        lines = codex.ensure_api_provider(content.splitlines(), "https://example.test/v1")
        return tomllib.loads("\n".join(lines))

    @requires_tomllib
    def test_commented_header_after_provider_survives(self) -> None:
        # Given a table header with a trailing comment right after the managed provider.
        document = self.provider_update(
            '[model_providers.codex_api]\nname = "old"\n\n[profiles.work] # work profile\nmodel = "x"\n'
        )
        # Then the profile is kept, and the provider is rewritten.
        self.assertEqual(document["profiles"]["work"], {"model": "x"})
        self.assertEqual(document["model_providers"]["codex_api"]["base_url"], "https://example.test/v1")

    @requires_tomllib
    def test_commented_provider_header_is_replaced_in_place(self) -> None:
        # Given the managed provider header itself carrying a comment and quoted key parts.
        document = self.provider_update('[ model_providers . "codex_api" ] # gateway\nname = "old"\n')
        # Then it is replaced instead of declared a second time.
        self.assertEqual(document["model_providers"]["codex_api"]["name"], "codex_api")

    @requires_tomllib
    def test_multiline_string_is_not_parsed_as_config(self) -> None:
        # Given instructions whose text contains config-looking lines.
        text = 'notify = ["x"]\n[model_providers.codex_api]\nmodel_provider = "codex_api"'
        content = f'developer_instructions = """\n{text}\n"""\n'
        lines = codex.ensure_notify(content.splitlines(), Path("/codex"))
        lines = codex.ensure_api_provider(lines, "https://example.test/v1")
        lines = codex.ensure_oauth_provider(lines)
        document = tomllib.loads("\n".join(lines))
        # Then the text is untouched, and the real top-level keys are added.
        self.assertEqual(document["developer_instructions"], text + "\n")
        self.assertEqual(document["notify"][1], str(Path("/codex") / "codex-gotify-notify.py"))
        self.assertIn("codex_api", document["model_providers"])


    def test_unparsable_value_does_not_hide_later_tables(self) -> None:
        # Given a typo tomllib rejects, then a multiline inline table (TOML 1.1).
        lines = ["model = oops", "tui = {", "  theme = 1,", "}", "[profiles.work]", 'model = "x"']
        # Then each value ends where its brackets balance, and the table is still found.
        self.assertEqual(toml_edit.toml_statement_starts(lines), [0, 1, 4, 5])
        self.assertEqual(toml_edit.find_first_toml_section_idx(lines), 4)


@requires_tomllib
class CodexNotifyPathTests(TestCase):
    def render_notify(self, python_bin: str, codex_dir: str) -> list:
        with patch.object(codex.sys, "executable", python_bin):
            lines = codex.ensure_notify([], PureWindowsPath(codex_dir)
                                                     if "\\" in codex_dir else Path(codex_dir))
        return tomllib.loads("\n".join(lines))["notify"]

    def test_windows_paths_round_trip(self) -> None:
        # Given the paths a PowerShell install produces; "\P" is not a valid TOML escape.
        notify = self.render_notify(r"C:\Python312\python.exe", r"C:\Users\me\.codex")
        # Then the written array parses back to the same paths.
        self.assertEqual(notify, [r"C:\Python312\python.exe", r"C:\Users\me\.codex\codex-gotify-notify.py"])

    def test_quotes_in_paths_round_trip(self) -> None:
        notify = self.render_notify('/opt/py "3"/bin/python', "/home/me/.codex")
        self.assertEqual(notify, ['/opt/py "3"/bin/python', "/home/me/.codex/codex-gotify-notify.py"])


class CodexSharedSkillOverrideTests(TestCase):
    """Codex keeps its bundled skill-creator; the ~/.agents/skills copy is off in Codex only."""

    skills_dir = Path("/home/me/.agents/skills")
    shared = str(skills_dir / "skill-creator" / "SKILL.md")

    def entries(self, original: str) -> list[dict]:
        lines = codex.ensure_shared_skills_disabled(original.splitlines(), self.skills_dir)
        return tomllib.loads("\n".join(lines)).get("skills", {}).get("config", [])

    @requires_tomllib
    def test_shared_copy_is_disabled_by_path(self) -> None:
        # Disabling by name would also hide Codex's bundled copy, so only the path is used.
        self.assertEqual(self.entries('model = "x"\n'), [{"path": self.shared, "enabled": False}])

    @requires_tomllib
    def test_existing_entry_is_reused_and_reenabling_is_undone(self) -> None:
        original = f'[[skills.config]]\npath = "{self.shared}"\nenabled = true # mine\n'
        self.assertEqual(self.entries(original), [{"path": self.shared, "enabled": False}])

    @requires_tomllib
    def test_entry_without_enabled_gets_it(self) -> None:
        original = f'[[skills.config]]\npath = "{self.shared}"\n\n[profiles.work]\nmodel = "y"\n'
        lines = codex.ensure_shared_skills_disabled(original.splitlines(), self.skills_dir)
        saved = tomllib.loads("\n".join(lines))
        self.assertEqual(saved["skills"]["config"], [{"path": self.shared, "enabled": False}])
        self.assertEqual(saved["profiles"]["work"]["model"], "y")

    @requires_tomllib
    def test_other_skill_entries_are_kept(self) -> None:
        original = ('[[skills.config]]\nname = "imagegen"\nenabled = false\n\n'
                    '[[skills.config]]\npath = "/elsewhere/SKILL.md"\nenabled = true\n')
        self.assertEqual(self.entries(original), [
            {"name": "imagegen", "enabled": False},
            {"path": "/elsewhere/SKILL.md", "enabled": True},
            {"path": self.shared, "enabled": False},
        ])

    @requires_tomllib
    def test_entry_with_both_selectors_is_not_reused(self) -> None:
        # Codex ignores an entry naming both a path and a name, so a valid one is added.
        original = f'[[skills.config]]\npath = "{self.shared}"\nname = "skill-creator"\nenabled = true\n'
        self.assertEqual(self.entries(original), [
            {"path": self.shared, "name": "skill-creator", "enabled": True},
            {"path": self.shared, "enabled": False},
        ])

    @requires_tomllib
    def test_inline_skills_config_is_left_alone(self) -> None:
        # An inline array cannot be extended with [[skills.config]]; appending would
        # make the whole file invalid, so the file is kept and the user is told.
        for original in (
            '[skills]\nconfig = [{ path = "/x/SKILL.md", enabled = false }]\n',
            'skills = { config = [] }\n',
            'skills.config = []\n',
            '[skills.config]\nx = 1\n',
            '[skills.config.x]\ny = 1\n',
        ):
            for fallback in (False, True):
                with self.subTest(original=original, fallback=fallback), \
                        patch.object(toml_edit, "tomllib", None if fallback else tomllib), \
                        contextlib.redirect_stderr(io.StringIO()) as err:
                    lines = codex.ensure_shared_skills_disabled(original.splitlines(), self.skills_dir)
                self.assertEqual(lines, original.splitlines())
                self.assertIn("skill-creator", err.getvalue())

    @requires_tomllib
    def test_sub_table_of_an_entry_is_not_mistaken_for_inline_config(self) -> None:
        original = f'[[skills.config]]\npath = "{self.shared}"\n[skills.config.extra]\nx = 1\n'
        for fallback in (False, True):
            with self.subTest(fallback=fallback), \
                    patch.object(toml_edit, "tomllib", None if fallback else tomllib):
                lines = codex.ensure_shared_skills_disabled(original.splitlines(), self.skills_dir)
            saved = tomllib.loads("\n".join(lines))
            self.assertEqual(saved["skills"]["config"],
                             [{"path": self.shared, "enabled": False, "extra": {"x": 1}}])

    @requires_tomllib  # checks a safeguard that only runs with tomllib
    def test_an_edit_that_would_break_the_file_is_dropped(self) -> None:
        # A table under skills.config that the static check does not catch.
        original = '[skills.config.x]\ny = 1\n'
        with patch.object(codex, "skills_config_is_static", return_value=False), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            lines = codex.ensure_shared_skills_disabled(original.splitlines(), self.skills_dir)
        self.assertEqual(lines, original.splitlines())
        self.assertIn("skill-creator", err.getvalue())

    @requires_tomllib  # checks a safeguard that only runs with tomllib
    def test_inline_entry_that_already_disables_it_is_accepted(self) -> None:
        original = f'[skills]\nconfig = [{{ path = "{self.shared}", enabled = false }}]\n'
        with contextlib.redirect_stderr(io.StringIO()) as err:
            lines = codex.ensure_shared_skills_disabled(original.splitlines(), self.skills_dir)
        self.assertEqual(lines, original.splitlines())
        self.assertEqual(err.getvalue(), "")

    def test_second_run_changes_nothing(self) -> None:
        once = codex.ensure_shared_skills_disabled([], self.skills_dir)
        self.assertEqual(codex.ensure_shared_skills_disabled(once, self.skills_dir), once)

    @requires_tomllib
    def test_full_config_install_disables_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".codex").mkdir()
            codex.ensure_config(make_context(Path(tmp), env=GATEWAY_ENV, stamp="skills-test"),
                                Path(tmp) / ".codex")
            saved = tomllib.loads((Path(tmp) / ".codex" / "config.toml").read_text(encoding="utf-8"))
        shared = str(Path(tmp) / ".agents" / "skills" / "skill-creator" / "SKILL.md")
        self.assertEqual(saved["skills"]["config"], [{"path": shared, "enabled": False}])


if __name__ == "__main__":
    unittest.main()
