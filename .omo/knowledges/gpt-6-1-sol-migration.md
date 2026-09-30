# GPT-6.1 Sol migration

- On 2026-09-30, every model slot that used `gpt-6-sol` moved to `gpt-6.1-sol`. GPT-6 Luna and Astra stay the same.
- Official source: https://developers.openai.com/api/docs/models/gpt-6.1-sol. The GPT-6 Sol page now points to GPT-6.1 Sol as the newer Sol model.
- Official specs: 1,050,000-token context window, 128,000 max output, text/image input, text output, and reasoning efforts `low`/`medium`/`high`/`xhigh`/`max`. Knowledge cutoff is 2026-04-30.
- Standard USD prices per 1M tokens: input 2, cached input 0.1 (5% of input, down from GPT-6 Sol's 0.2), cache writes 2.5, output 10. Prompts over 272K input tokens cost 2x input/cache and 1.5x output for the whole request, so the existing 272K input budget stays: OpenCode keeps `context 400000 / input 272000 / output 128000`, and OMP keeps `contextWindow 272000`.
- Local discovery on 2026-09-30: OpenCode lists `openai/gpt-6.1-sol` and `openai/gpt-6.1-sol-fast` for OAuth. OMP's `~/.omp/agent/models.db` cache already has `gpt-6.1-sol`.
- Files changed: `opencode.jsonc` (`codex` catalog entry and `openai` OAuth limit overrides, including `-fast`), `omo.jsonc` (all Sol agents/categories in both `[opencode]` and `[native]`; OAuth install rewrites the prefix to `openai/` or `chatgpt-subscription/`), `omp_config.yml`, `omp_models.yaml`, `omp_models_oauth.yaml`, `tokscale_model_alias.json` (added `gpt-6.1-sol` aliases, kept `gpt-6-sol` aliases for history), and tests.
- In OAuth mode, `pull.py` preserves an installed `provider.codex` object, so an already installed OAuth OpenCode config keeps its old `codex/gpt-6-sol` entry until it is cleaned up manually or reinstalled in API mode.

## Verification

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m json.tool opencode.jsonc > /dev/null
python3 -m json.tool tokscale_model_alias.json > /dev/null
git diff --check
opencode models codex --pure | grep 'codex/gpt-6.1-sol'
```

Expected: 98 tests pass, JSON parses, no whitespace errors, and the model ID is listed. The OMP check in `omp-model-sync.md` should list `codex_api` IDs `gpt-5.4`, `gpt-6-luna`, `gpt-6.1-sol`. Model discovery does not prove the gateway or subscription can actually use the model.
