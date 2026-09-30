# pull.py on Python 3.10 (tomllib fallback)

GitHub issue #3: `pull.py` did `import tomllib` at module level, so the
`curl ... | python3` installer crashed on Python < 3.11 (e.g. Ubuntu 22.04's
`/usr/bin/python3` is 3.10). A third-party `tomli` is not an option because the
installer must run with a bare interpreter.

`pull.py` only needs TOML for two small questions, now wrapped in helpers that
use `tomllib` when present and a stdlib scanner otherwise:

- `toml_assignment_is_complete(key, value)` — is a (possibly multiline)
  `notify = [...]` value finished? Fallback `toml_value_is_complete()` tracks
  bracket depth, `#` comments, and `"`/`'`/`"""`/`'''` strings (with backslash
  escapes in basic strings only).
- `read_toml_string_assignment(line, key)` — string value of a single-line
  `model_provider = "..."`. Invalid lines now return `None` instead of raising
  (the OAuth path previously had no `try`).

Minimum supported Python is 3.10: `X | None` annotations are evaluated at
definition time, so 3.9 still fails without `from __future__ import annotations`.

Test caveat: most existing tests use `TestCase.enterContext` or `tomllib` as an
oracle, both 3.11+, so the full suite only runs on 3.11+. Only
`tests/test_pull_toml_fallback.py` runs on 3.10, and it forces the fallback on
any version by patching `pull.tomllib` to `None`.

Verification:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'      # 3.11+: all OK
/usr/bin/python3.10 -m unittest tests/test_pull_toml_fallback.py   # OK
```

End-to-end on 3.10: run `pull.py` with `env -i HOME=<scratch> PATH=<dir with only git>
INSTALL_ALL=1 NO_BACKUP=1 CODEX_BASE_URL=https://example.test/v1`, twice, then
with `--oauth`, then again. Expected: exit 0 each run, the second run is byte-identical,
and the resulting `config.toml` parses with `tomllib` on 3.11+.
