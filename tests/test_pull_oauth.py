"""OAuth routing tests use synthetic configs in temporary directories only."""

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pull_oauth", ROOT / "pull.py")
pull = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pull)


class OAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(pull, "NO_BACKUP", False))

    def test_codex_comments_only_top_level_gateway_assignment(self):
        lines = ['model_provider = "codex_api" # gateway', '[profiles.work]',
                 'model_provider = "codex_api"']
        result = pull.ensure_codex_oauth_provider_config(lines)
        self.assertEqual(result, ['# ' + lines[0], *lines[1:]])
        self.assertEqual(pull.ensure_codex_oauth_provider_config(result), result)
        for original in ([], ['model = "gpt-5.5"'], ['model_provider = "openai"'],
                         ['model_provider = "local"']):
            self.assertEqual(pull.ensure_codex_oauth_provider_config(original), original)
        self.assertEqual(pull.ensure_codex_oauth_provider_config(
            ["  model_provider = 'codex_api'"]), ["#   model_provider = 'codex_api'"])

    def test_codex_install_round_trip_preserves_provider_and_auth(self):
        config = self.tmp / 'config.toml'
        auth = self.tmp / 'auth.json'
        auth.write_text('{}')
        with patch.dict(os.environ, {'CODEX_BASE_URL': 'https://example.invalid/v1'}):
            pull.ensure_codex_config(self.tmp, 'api')
            original = config.read_text()
            pull.ensure_codex_config(self.tmp, 'oauth', oauth=True)
            parsed = tomllib.loads(config.read_text())
            self.assertNotIn('model_provider', parsed)
            self.assertIn('codex_api', parsed['model_providers'])
            self.assertEqual(config.with_suffix('.toml.bak-oauth').read_text(), original)
            before = config.read_text()
            pull.ensure_codex_config(self.tmp, 'again', oauth=True)
            self.assertEqual(config.read_text(), before)
            pull.ensure_codex_config(self.tmp, 'api-again')
            self.assertEqual(tomllib.loads(config.read_text())['model_provider'], 'codex_api')
        self.assertEqual(auth.read_text(), '{}')

    def test_codex_repeated_switches_do_not_accumulate_comments(self):
        lines = ['model_provider = "codex_api" # gateway', '[profiles.work]',
                 '# model_provider = "codex_api"']
        with patch.dict(os.environ, {'CODEX_BASE_URL': 'https://example.invalid/v1'}):
            for _ in range(3):
                lines = pull.ensure_codex_oauth_provider_config(lines)
                lines = pull.ensure_codex_api_provider_config(lines)
                self.assertEqual(tomllib.loads('\n'.join(lines))['model_provider'], 'codex_api')
                self.assertEqual(lines.count('model_provider = "codex_api"'), 1)
                self.assertEqual(lines.count('# model_provider = "codex_api"'), 1)

    def test_opencode_preserves_existing_provider_with_jsonc(self):
        dst = self.tmp / 'opencode.jsonc'
        dst.write_text('''{
          // Synthetic provider, no real credentials.
          "provider": {"codex": {"options": {"baseURL": "https://example.invalid/v1",},},},
        }''')
        original = dst.read_text()
        pull.install_opencode_config_files(ROOT, self.tmp, 'oauth', oauth=True)
        parsed = json.loads(dst.read_text())
        self.assertEqual(parsed['provider']['codex'],
                         {'options': {'baseURL': 'https://example.invalid/v1'}})
        self.assertEqual(parsed['plugin'], json.loads((ROOT / 'opencode.jsonc').read_text())['plugin'])
        self.assertEqual(dst.with_suffix('.jsonc.bak-oauth').read_text(), original)

    def test_opencode_does_not_add_missing_provider(self):
        for existing in (None, '{}', '{"provider": {}}'):
            with self.subTest(existing=existing):
                directory = self.tmp / str(len(list(self.tmp.iterdir())))
                directory.mkdir()
                if existing is not None:
                    (directory / 'opencode.jsonc').write_text(existing)
                pull.install_opencode_config_files(ROOT, directory, 'oauth', oauth=True)
                parsed = json.loads((directory / 'opencode.jsonc').read_text())
                self.assertNotIn('codex', parsed['provider'])
                pull.install_opencode_config_files(ROOT, directory, 'api')
                self.assertIn('codex', json.loads((directory / 'opencode.jsonc').read_text())['provider'])

    def test_opencode_legacy_json_provider_is_preserved(self):
        (self.tmp / 'opencode.json').write_text('{"provider":{"codex":{"name":"Retained"}}}')
        pull.install_opencode_config_files(ROOT, self.tmp, 'oauth', oauth=True)
        self.assertEqual(json.loads((self.tmp / 'opencode.jsonc').read_text())['provider']['codex'],
                         {'name': 'Retained'})

    def test_invalid_opencode_is_not_overwritten(self):
        dst = self.tmp / 'opencode.jsonc'
        dst.write_text('{ invalid')
        with self.assertRaises(ValueError):
            pull.install_opencode_config_files(ROOT, self.tmp, 'oauth', oauth=True)
        self.assertEqual(dst.read_text(), '{ invalid')

    def test_omo_rewrites_model_prefix_preserving_ids(self):
        pull.install_omo_config(ROOT, self.tmp, 'oauth', oauth=True)
        actual = (self.tmp / 'omo.jsonc').read_text()
        self.assertEqual(actual, (ROOT / 'omo.jsonc').read_text().replace('"codex/', '"openai/'))
        pull.install_omo_config(ROOT, self.tmp, 'api')
        self.assertEqual((self.tmp / 'omo.jsonc').read_text(), (ROOT / 'omo.jsonc').read_text())

    def test_omp_native_roles_and_empty_custom_catalog(self):
        pull.install_omp_config(ROOT / 'omp_config.yml', self.tmp / 'config.yml', 'oauth', oauth=True)
        content = (self.tmp / 'config.yml').read_text()
        self.assertEqual(content, (ROOT / 'omp_config.yml').read_text().replace('codex_api/', 'openai-codex/'))
        dst = self.tmp / 'models.yml'
        dst.write_text('providers: {}\n')
        with patch.dict(os.environ, {}, clear=True), contextlib.redirect_stderr(io.StringIO()) as stderr:
            pull.backup_and_install_omp_models(ROOT / 'omp_models.yaml', dst, 'oauth', oauth=True)
        self.assertEqual(dst.read_text(), 'providers: {}\n')
        self.assertEqual(stderr.getvalue(), '')
        with patch.dict(os.environ, {'CODEX_BASE_URL': 'https://example.invalid/v1'}):
            pull.backup_and_install_omp_models(ROOT / 'omp_models.yaml', dst, 'api')
        self.assertIn('codex_api:', dst.read_text())

    def test_oauth_environment_warnings_exclude_gateway(self):
        with patch.dict(os.environ, {}, clear=True), contextlib.redirect_stdout(io.StringIO()) as output:
            pull.warn_missing_required_env_vars(oauth=True)
        self.assertNotIn('CODEX_BASE_URL', output.getvalue())
        self.assertNotIn('CODEX_API_KEY', output.getvalue())
        self.assertIn('GITHUB_PERSONAL_ACCESS_TOKEN', output.getvalue())

    def test_main_routes_all_outputs_without_touching_auth(self):
        for name in ('get_config_dir', 'get_codex_dir', 'get_claude_config_dir',
                     'get_omp_agent_dir', 'get_tokscale_config_dir'):
            if hasattr(pull, name):
                self.enterContext(patch.object(pull, name, return_value=self.tmp / name))
        self.enterContext(patch.object(Path, 'home', return_value=self.tmp))
        for name in ('install_claude_plugin', 'install_tokscale_model_aliases'):
            if hasattr(pull, name):
                self.enterContext(patch.object(pull, name))

        def clone(command, **kwargs):
            destination = Path(command[-1])
            destination.mkdir()
            for name in ('opencode.jsonc', 'omo.jsonc', 'omp_config.yml', 'omp_models.yaml'):
                shutil.copy2(ROOT / name, destination / name)
            return subprocess.CompletedProcess(command, 0)

        self.enterContext(patch.object(pull.subprocess, 'run', side_effect=clone))
        with patch.dict(os.environ, {'CODEX_BASE_URL': 'https://example.invalid/v1'}):
            pull.main([])
            pull.main(['--oauth'])
            codex = tomllib.loads((self.tmp / 'get_codex_dir/config.toml').read_text())
            self.assertNotIn('model_provider', codex)
            self.assertIn('codex', json.loads((self.tmp / 'get_config_dir/opencode.jsonc').read_text())['provider'])
            self.assertNotIn('"codex/', (self.tmp / '.omo/omo.jsonc').read_text())
            self.assertNotIn('codex_api/', (self.tmp / 'get_omp_agent_dir/config.yml').read_text())
            self.assertEqual((self.tmp / 'get_omp_agent_dir/models.yml').read_text(), 'providers: {}\n')
            pull.main([])
            codex = tomllib.loads((self.tmp / 'get_codex_dir/config.toml').read_text())
            self.assertEqual(codex['model_provider'], 'codex_api')
            self.assertIn('"codex/', (self.tmp / '.omo/omo.jsonc').read_text())
            self.assertIn('codex_api/', (self.tmp / 'get_omp_agent_dir/config.yml').read_text())

    def test_argument_parser(self):
        self.assertFalse(pull.parse_args([]).oauth)
        self.assertTrue(pull.parse_args(['--oauth']).oauth)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            pull.parse_args(['--unknown'])


if __name__ == '__main__':
    unittest.main()
