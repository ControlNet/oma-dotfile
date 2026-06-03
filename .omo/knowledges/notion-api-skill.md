# Notion API Skill Installation

- Installed upstream skill: `https://github.com/intellectronica/agent-skills/tree/main/skills/notion-api`
- Vendored from commit: `9b0e00ad1b941165e2506545bbfddafa34cf2cb8`
- Local path: `skills/notion-api/`
- Included files: `SKILL.md` plus `references/block-types.md`, `references/filters-and-sorts.md`, `references/property-types.md`, and `references/rich-text.md`.
- No `opencode.jsonc` change is required; `pull.py` copies repo-local `skills/` into the user opencode config and merge-copies them into Codex skills.
- Runtime expectation: the skill uses `curl`, `jq`, and `NOTION_API_TOKEN` for REST calls. Never record actual Notion token values in this repo.
- Local normalization: upstream reference examples using the old API key env-var spelling were changed to `NOTION_API_TOKEN` to match `SKILL.md`.

Verification commands used:

```bash
python3 - <<'PYVERIFY'
from pathlib import Path
root = Path('skills/notion-api')
expected = [
    root / 'SKILL.md',
    root / 'references/block-types.md',
    root / 'references/filters-and-sorts.md',
    root / 'references/property-types.md',
    root / 'references/rich-text.md',
]
missing = [str(path) for path in expected if not path.is_file()]
assert not missing, f'missing files: {missing}'
skill = (root / 'SKILL.md').read_text(encoding='utf-8')
assert skill.startswith('---\n')
assert 'name: notion-api' in skill
for path in expected[1:]:
    assert path.read_text(encoding='utf-8').strip()
print('notion-api skill structure ok')
PYVERIFY
python3 skills/secret-guard/scripts/scan_secrets.py skills/notion-api README.md .omo/knowledges/notion-api-skill.md
```
