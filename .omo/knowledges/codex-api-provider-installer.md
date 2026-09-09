# Codex API Provider Installer

`pull.py` configures `~/.codex/config.toml` with both the Codex notify hook and
the Codex API model provider.

Provider behavior:

- Source rechecked on 2026-09-09: injection requires a non-empty
  `CODEX_BASE_URL` after stripping whitespace. It does not require checking
  `CODEX_API_KEY` before modifying the provider configuration.
- If `[model_providers.codex_api]` already exists, the top-level provider
  selection is preserved, including an absent or commented-out assignment.
  This treats an existing but unselected provider as manually disabled.
- Top-level `model_provider` is set to `"codex_api"` only when the provider
  section does not already exist. Existing section detection uses the same
  stripped, exact section header as the section replacement helper.
- `[model_providers.codex_api]` is created or replaced.
- `base_url` is written from the current `CODEX_BASE_URL` environment variable.
- `env_key` remains `"CODEX_API_KEY"` because Codex can resolve the API key from
  the environment.
- `wire_api` is set to `"responses"`.
- If `CODEX_BASE_URL` is missing, provider injection is skipped with a warning;
  no hard-coded URL or placeholder is written into Codex config.

Expected generated TOML fragment on first installation:

```toml
model_provider = "codex_api"

[model_providers.codex_api]
name = "codex_api"
base_url = "<CODEX_BASE_URL value>"
env_key = "CODEX_API_KEY"
wire_api = "responses"
```

Manual verification command used:

```bash
CODEX_BASE_URL='https://example.test/v1' python3 - <<'PY'
import importlib.util
import tempfile
from pathlib import Path

spec = importlib.util.spec_from_file_location('pull', 'pull.py')
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

with tempfile.TemporaryDirectory() as tmp:
    codex_dir = Path(tmp) / '.codex'
    codex_dir.mkdir()
    config = codex_dir / 'config.toml'
    config.write_text(
        'notify = ["old", "hook"]\n'
        'model_provider = "codex_api"\n'
        'model = "keep-me"\n\n'
        '[model_providers.codex_api]\n'
        'name = "old"\n'
        'base_url = "https://old.example/v1"\n'
        'env_key = "OLD_KEY"\n'
        'wire_api = "chat"\n\n'
        '[profile.default]\n'
        'notify = ["nested", "hook"]\n'
        'approval_policy = "on-request"\n',
        encoding='utf-8',
    )
    module.ensure_codex_config(codex_dir, 'manualqa')
    content = config.read_text(encoding='utf-8')
    assert content.count('notify = ') == 1, content
    assert 'codex-gotify-notify.py' in content, content
    assert 'model_provider = "codex_api"' in content, content
    assert content.count('[model_providers.codex_api]') == 1, content
    assert 'name = "codex_api"' in content, content
    assert 'base_url = "https://example.test/v1"' in content, content
    assert 'env_key = "CODEX_API_KEY"' in content, content
    assert 'wire_api = "responses"' in content, content
    assert 'base_url = "https://old.example/v1"' not in content, content
    assert 'model = "keep-me"' in content, content
    assert 'approval_policy = "on-request"' in content, content
print('codex provider and notify injection: ok')
PY
```

Regression verification (2026-09-09):

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

Result: 18 tests passed. `tests/test_codex_provider_config.py` uses synthetic
TOML and reserved test URLs, writes only temporary files, and covers absent,
commented-out, alternative, and active top-level selections; nested profile
selection; provider URL updates; repeat-run idempotence; first installation;
and an empty URL. The three disabled-selection cases failed before the fix.
