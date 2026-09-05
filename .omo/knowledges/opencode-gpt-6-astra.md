# GPT-6 Astra in OpenCode

- Added `codex/gpt-6-astra` to `opencode.jsonc` on 2026-09-05.
- Official source: https://developers.openai.com/api/docs/models/gpt-6-astra
- The model supports text/image input, text output, reasoning, and tool calls. Its context window is 1,050,000 tokens, maximum input is 922,000 tokens, and maximum output is 128,000 tokens.
- User preference overrides the configured context window to 382,000 tokens, with maximum output 128,000 tokens, in both repository and local OpenCode configuration. As with existing entries, no separate input cap is configured; OpenCode manages the input budget.
- A format review removed the redundant `tool_call: true` field and the previously imposed 254,000-token input cap. Explicit `reasoning: true` remains intentional: local inspection initially reported `capabilities.reasoning: false` for Sol without that declaration. A subsequent fix added the declaration to all existing Codex models; see `opencode-reasoning-defaults.md`. `cost.cache_write` also remains as documented pricing metadata. Indentation, modalities, and the five configured reasoning variants follow the existing Sol entry.
- Supported reasoning variants are `low`, `medium`, `high`, `xhigh`, and `max`.
- Standard USD prices per million tokens are input 10, output 50, cached input 1, and cache writes 12.5. The official long-context surcharge starts above 272K input tokens; the configured costs describe standard rates only.
- User-level OpenCode configuration is a separate file, not a symlink. The local `~/.config/opencode/opencode.jsonc` also received this model, with a timestamped `.bak-astra-*` backup and all existing settings preserved.
- This change adds a selectable model; it does not change agent assignments. The OMP catalog was outside this OpenCode-only change and does not yet mirror Astra.

## Verification

```bash
python -m json.tool opencode.jsonc > /dev/null
git diff --check
opencode models codex --pure | rg '^codex/gpt-6-astra$'
```

Expected: valid JSON, no whitespace errors, and the exact model ID in the OpenCode model list. Model discovery does not verify that the configured upstream grants access to the model.
