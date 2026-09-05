# OpenCode reasoning capabilities and defaults

- All configured GPT models under `provider.codex.models` support reasoning and must explicitly declare `"reasoning": true`. Custom model entries can otherwise resolve with `capabilities.reasoning: false`, even when they define reasoning variants.
- On 2026-09-05, added the missing declaration to six existing repository models and nine existing user-level models. Astra already declared it. The user-level catalog additionally contains GPT 5.1 Codex Mini, GPT 5.2, and GPT 5.3 Codex.
- `provider.codex.options.reasoningEffort` remains `"medium"`. Per-model default options are unnecessary for this requested change.
- The user explicitly requested fixing the missing capability declarations while retaining the existing default. OMO agent/category reasoning overrides and selectable variants remain unchanged.

## Verification

```bash
git diff --check
opencode models codex --pure --verbose
```

Expected: no whitespace errors and `capabilities.reasoning: true` for every Codex model. The core configuration retains `provider.codex.options.reasoningEffort: "medium"`. Model inspection does not verify upstream inference access.
