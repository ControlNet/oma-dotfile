# Codex Notify Installer Overwrite Behavior

`pull.py` always configures the Codex notify hook during installation. The old
`SETUP_NOTIFY_HOOKS` opt-out and `SETUP_NOTIFY_HOOKS_FORCE` overwrite gate were
removed.

`ensure_codex_config()` now calls `ensure_codex_notify_config_lines()` and treats
`notify = ...` as installer-owned:

- If `~/.codex/config.toml` is missing, it creates the file with a top-level
  Codex notify line.
- If any `notify = ...` lines exist, it removes duplicates/nested entries and
  writes one top-level Codex notify line.
- If no `notify = ...` exists, it inserts one before the first TOML section, or
  at EOF when there are no sections.

Manual verification command used:

```bash
python3 - <<'PY'
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
    config.write_text('notify = ["old", "hook"]\nmodel = "old-model"\n\n[profile.default]\nnotify = ["other", "nested"]\napproval_policy = "on-request"\n', encoding='utf-8')
    module.ensure_codex_config(codex_dir, 'manualqa')
    content = config.read_text(encoding='utf-8')
    assert content.count('notify = ') == 1, content
    assert 'codex-gotify-notify.py' in content, content
    assert content.index('notify = ') < content.index('[profile.default]'), content
    assert 'model = "old-model"' in content, content
    assert 'approval_policy = "on-request"' in content, content
print('codex notify overwrite behavior: ok')
PY
```
