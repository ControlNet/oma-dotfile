"""OAuth routing tests use synthetic configs in temporary directories only."""

import contextlib
import io
import json
import shutil
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from omadotfile import cli
from omadotfile.agents import claude, codex, omo, omo_native, omp, opencode, tokscale
from omadotfile.agents.base import Component
from omadotfile.constants import OMP_MODELS, OMP_MODELS_OAUTH
from omadotfile.core.jsonc import read_jsonc_object
from omadotfile.features import skills, wakatime
from omadotfile.console import use_console
from support import ROOT, Recorder, TestCase, make_context, requires_tomllib, tomllib

GATEWAY_URL = 'https://example.invalid/v1'


def install_files(component: Component, ctx, target: Path) -> None:
    """Install a component's `files` into target, as its step does before `configure`."""
    target.mkdir(parents=True, exist_ok=True)
    with use_console(Recorder()):
        for spec in component.files:
            component.install_file(ctx, spec, target)


class OAuthTests(TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def context(self, stamp, oauth=False, env=None):
        return make_context(self.tmp, stamp=stamp, oauth=oauth,
                            env={'CODEX_BASE_URL': GATEWAY_URL} if env is None else env)

    def codex_config(self, stamp, oauth=False):
        with use_console(Recorder()):
            codex.ensure_config(self.context(stamp, oauth=oauth), self.tmp)

    def test_codex_comments_only_top_level_gateway_assignment(self):
        lines = ['model_provider = "codex_api" # gateway', '[profiles.work]',
                 'model_provider = "codex_api"']
        result = codex.ensure_oauth_provider(lines)
        self.assertEqual(result, ['# ' + lines[0], *lines[1:]])
        self.assertEqual(codex.ensure_oauth_provider(result), result)
        for original in ([], ['model = "gpt-5.5"'], ['model_provider = "openai"'],
                         ['model_provider = "local"']):
            self.assertEqual(codex.ensure_oauth_provider(original), original)
        self.assertEqual(codex.ensure_oauth_provider(
            ["  model_provider = 'codex_api'"]), ["#   model_provider = 'codex_api'"])

    @requires_tomllib
    def test_codex_install_round_trip_preserves_provider_and_auth(self):
        config = self.tmp / 'config.toml'
        auth = self.tmp / 'auth.json'
        auth.write_text('{}')
        self.codex_config('api')
        original = config.read_text()
        self.codex_config('oauth', oauth=True)
        parsed = tomllib.loads(config.read_text())
        self.assertNotIn('model_provider', parsed)
        self.assertIn('codex_api', parsed['model_providers'])
        self.assertEqual(config.with_suffix('.toml.bak-oauth').read_text(), original)
        before = config.read_text()
        self.codex_config('again', oauth=True)
        self.assertEqual(config.read_text(), before)
        self.codex_config('api-again')
        self.assertEqual(tomllib.loads(config.read_text())['model_provider'], 'codex_api')
        self.assertEqual(auth.read_text(), '{}')

    @requires_tomllib
    def test_codex_repeated_switches_do_not_accumulate_comments(self):
        lines = ['model_provider = "codex_api" # gateway', '[profiles.work]',
                 '# model_provider = "codex_api"']
        for _ in range(3):
            lines = codex.ensure_oauth_provider(lines)
            lines = codex.ensure_api_provider(lines, GATEWAY_URL)
            self.assertEqual(tomllib.loads('\n'.join(lines))['model_provider'], 'codex_api')
            self.assertEqual(lines.count('model_provider = "codex_api"'), 1)
            self.assertEqual(lines.count('# model_provider = "codex_api"'), 1)

    @requires_tomllib
    def test_codex_oauth_disables_quoted_and_multiline_selectors(self):
        for selector in (['"model_provider" = "codex_api"'],
                         ['model_provider = """', 'codex_api"""']):
            with self.subTest(selector=selector):
                lines = [*selector, '[profiles.work]', 'model = "gpt"']
                result = codex.ensure_oauth_provider(lines)
                # The gateway is no longer selected and later tables survive.
                parsed = tomllib.loads('\n'.join(result))
                self.assertNotIn('model_provider', parsed)
                self.assertEqual(parsed['profiles'], {'work': {'model': 'gpt'}})
                self.assertEqual(codex.ensure_oauth_provider(result), result)
                # Switching back restores one selector instead of adding a second.
                restored = codex.ensure_api_provider(result, GATEWAY_URL)
                self.assertEqual(tomllib.loads('\n'.join(restored))['model_provider'], 'codex_api')
                self.assertFalse(any(line.lstrip('# ').startswith(('model_provider', '"model_provider"'))
                                     for line in restored[1:]), restored)

    def test_opencode_preserves_existing_provider_with_jsonc(self):
        dst = self.tmp / 'opencode.jsonc'
        dst.write_text('''{
          // Synthetic provider, no real credentials.
          "provider": {"codex": {"options": {"baseURL": "https://example.invalid/v1",},},},
        }''')
        original = dst.read_text()
        install_files(opencode.OpenCode(), self.context('oauth', oauth=True), self.tmp)
        parsed = json.loads(dst.read_text())
        self.assertEqual(parsed['provider']['codex'],
                         {'options': {'baseURL': 'https://example.invalid/v1'}})
        for model in ('gpt-6.1-sol', 'gpt-6-luna', 'gpt-6.1-sol-fast', 'gpt-6-luna-fast'):
            self.assertEqual(parsed['provider']['openai']['models'][model]['limit'],
                             {'context': 400000, 'input': 272000, 'output': 128000})
        self.assertEqual(parsed['plugin'], json.loads((ROOT / 'config/opencode/opencode.jsonc').read_text())['plugin'])
        self.assertEqual(dst.with_suffix('.jsonc.bak-oauth').read_text(), original)

    def test_opencode_does_not_add_missing_provider(self):
        for existing in (None, '{}', '{"provider": {}}'):
            with self.subTest(existing=existing):
                directory = self.tmp / str(len(list(self.tmp.iterdir())))
                directory.mkdir()
                if existing is not None:
                    (directory / 'opencode.jsonc').write_text(existing)
                install_files(opencode.OpenCode(), self.context('oauth', oauth=True), directory)
                parsed = json.loads((directory / 'opencode.jsonc').read_text())
                self.assertNotIn('codex', parsed['provider'])
                install_files(opencode.OpenCode(), self.context('api'), directory)
                installed = json.loads((directory / 'opencode.jsonc').read_text())['provider']
                for model in ('gpt-6.1-sol', 'gpt-6-luna'):
                    self.assertEqual(installed['codex']['models'][model]['limit'],
                                     {'context': 400000, 'input': 272000, 'output': 128000})

    def test_opencode_legacy_json_provider_is_preserved(self):
        (self.tmp / 'opencode.json').write_text('{"provider":{"codex":{"name":"Retained"}}}')
        install_files(opencode.OpenCode(), self.context('oauth', oauth=True), self.tmp)
        self.assertEqual(json.loads((self.tmp / 'opencode.jsonc').read_text())['provider']['codex'],
                         {'name': 'Retained'})

    def test_invalid_opencode_is_not_overwritten(self):
        dst = self.tmp / 'opencode.jsonc'
        dst.write_text('{ invalid')
        with self.assertRaises(ValueError):
            install_files(opencode.OpenCode(), self.context('oauth', oauth=True), self.tmp)
        self.assertEqual(dst.read_text(), '{ invalid')

    def test_omo_rewrites_model_prefix_preserving_ids(self):
        install_files(omo.OmoConfig(), self.context('oauth', oauth=True), self.tmp)
        actual = (self.tmp / 'omo.jsonc').read_text()
        # Native routing lives in its own block; see tests/test_omo_native.py.
        opencode = read_jsonc_object(self.tmp / 'omo.jsonc')['[opencode]']
        self.assertNotIn('"codex/', json.dumps(opencode))
        self.assertIn('"openai/gpt-6.1-sol"', actual)
        install_files(omo.OmoConfig(), self.context('api'), self.tmp)
        self.assertEqual((self.tmp / 'omo.jsonc').read_text(), (ROOT / 'config/omo/omo.jsonc').read_text())

    def test_omp_native_roles_and_model_overrides(self):
        install_files(omp.Omp(), self.context('oauth', oauth=True), self.tmp)
        content = (self.tmp / 'config.yml').read_text()
        self.assertEqual(content, (ROOT / 'config/omp/config.yml').read_text().replace('codex_api/', 'openai-codex/'))
        dst = self.tmp / 'models.yml'
        dst.write_text('providers: {}\n')
        with use_console(Recorder()) as printed:
            omp.install_models(self.context('oauth', oauth=True, env={}), self.tmp)
        self.assertEqual(dst.read_text(), (ROOT / 'config/omp/models.oauth.yml').read_text())
        for model in ('gpt-6.1-sol', 'gpt-6-luna', 'gpt-6.1-sol-fast', 'gpt-6-luna-fast'):
            self.assertIn(f'      {model}:\n        contextWindow: 272000\n        maxTokens: 128000', dst.read_text())
        self.assertEqual(printed.warnings, [])
        with use_console(Recorder()):
            omp.install_models(self.context('api'), self.tmp)
        self.assertIn('codex_api:', dst.read_text())

    def test_unreadable_omp_models_warn_and_leave_models_yml_alone(self):
        repo = self.tmp / 'repo'
        (repo / 'config' / 'omp').mkdir(parents=True)
        (repo / OMP_MODELS).write_text('providers: {}\n')
        dst = self.tmp / 'agent' / 'models.yml'
        for oauth, missing in ((True, OMP_MODELS_OAUTH), (False, None)):
            with self.subTest(oauth=oauth):
                if missing is None:
                    (repo / OMP_MODELS).unlink()
                    (repo / OMP_MODELS).mkdir()  # exists, but reading it fails
                    missing = OMP_MODELS
                ctx = make_context(self.tmp, repo=repo, oauth=oauth)
                with use_console(Recorder()) as printed:
                    omp.install_models(ctx, dst.parent)
                (warning,) = printed.warnings
                self.assertTrue(warning.startswith(f'Failed to read {repo / missing}: '), warning)
                self.assertFalse(dst.exists())

    def test_done_notes_name_logins_only_for_found_agents(self):
        ctx = make_context(self.tmp, oauth=True, found=('codex', 'claude'), stamp='20261107-120000')
        notes = cli.done_notes(ctx)
        self.assertIn('Log in with: codex login', notes)
        self.assertEqual(notes[-2:], ['Timestamp: 20261107-120000',
                                      'Backups: *.bak-20261107-120000 (keep last 1 per file)'])
        self.assertEqual(cli.done_notes(make_context(self.tmp, backup=False, stamp='s')), ['Timestamp: s'])

    def test_oauth_environment_warnings_exclude_gateway(self):
        with use_console(Recorder()) as printed:
            cli.warn_missing_required_env_vars({}, oauth=True)
        self.assertNotIn('CODEX_BASE_URL', printed.text)
        self.assertNotIn('CODEX_API_TOKEN', printed.text)
        self.assertIn('GITHUB_PERSONAL_ACCESS_TOKEN', printed.text)

    @requires_tomllib
    def test_main_routes_all_outputs_without_touching_auth(self):
        env = {
            'CODEX_BASE_URL': GATEWAY_URL,
            'CONFIG_DIR': str(self.tmp / 'config_dir'),
            'CODEX_DIR': str(self.tmp / 'codex_dir'),
            'CLAUDE_CONFIG_DIR': str(self.tmp / 'claude_config_dir'),
            'OMP_AGENT_DIR': str(self.tmp / 'omp_agent_dir'),
            'TOKSCALE_CONFIG_DIR': str(self.tmp / 'tokscale_config_dir'),
        }
        self.enterContext(patch.object(claude, 'install_plugins'))
        self.enterContext(patch.object(tokscale, 'install_model_aliases'))
        # The agent CLIs are never invoked here.
        plugins = self.enterContext(patch.object(wakatime, 'ensure_plugins'))
        # Nor npm and the omo-herdr-dag installer,
        self.enterContext(patch.object(omo_native, 'ensure_herdr_dag'))
        # nor npx and the skills CLI,
        self.enterContext(patch.object(skills, 'ensure_skills'))
        # nor git config, which would reach the real ~/.gitconfig.
        self.enterContext(patch.object(claude, 'ensure_commit_msg_hook'))
        # Detection belongs to the gating tests; this one routes every target.
        self.enterContext(patch.object(cli, 'detect_agents', return_value=frozenset(cli.AGENTS)))

        # A checkout holding only the files these routes read.
        repo = self.tmp / 'repo'
        repo.mkdir()
        for name in ('config/opencode/opencode.jsonc', 'config/omo/omo.jsonc', 'config/omp/config.yml',
                     'config/omp/models.yml', 'config/omp/models.oauth.yml'):
            (repo / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, repo / name)

        def main(argv):
            cli.main(argv, repo=repo, env=env, home=self.tmp, console=Recorder())

        main([])
        main(['--oauth'])
        codex_config = tomllib.loads((self.tmp / 'codex_dir/config.toml').read_text())
        self.assertNotIn('model_provider', codex_config)
        self.assertIn('codex', json.loads((self.tmp / 'config_dir/opencode.jsonc').read_text())['provider'])
        self.assertNotIn('"codex/', (self.tmp / '.omo/omo.jsonc').read_text())
        self.assertNotIn('codex_api/', (self.tmp / 'omp_agent_dir/config.yml').read_text())
        self.assertEqual((self.tmp / 'omp_agent_dir/models.yml').read_text(),
                         (ROOT / 'config/omp/models.oauth.yml').read_text())
        ctx = plugins.call_args.args[0]
        self.assertEqual((ctx.dirs['codex'], ctx.dirs['claude']),
                         (self.tmp / 'codex_dir', self.tmp / 'claude_config_dir'))
        main([])
        codex_config = tomllib.loads((self.tmp / 'codex_dir/config.toml').read_text())
        self.assertEqual(codex_config['model_provider'], 'codex_api')
        self.assertIn('"codex/', (self.tmp / '.omo/omo.jsonc').read_text())
        self.assertIn('codex_api/', (self.tmp / 'omp_agent_dir/config.yml').read_text())

    def test_argument_parser(self):
        self.assertFalse(cli.parse_args([]).oauth)
        self.assertTrue(cli.parse_args(['--oauth']).oauth)
        self.assertFalse(cli.parse_args([]).install_all)
        self.assertTrue(cli.parse_args(['--all']).install_all)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.parse_args(['--unknown'])


if __name__ == '__main__':
    unittest.main()
