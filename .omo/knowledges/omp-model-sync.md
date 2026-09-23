# OMP model synchronization

## Source of truth

- `opencode.jsonc` defines the `provider.codex.models` catalog, including model IDs, context/output limits, modalities, and costs.
- `omo.jsonc` defines the intended OpenCode model tier allocation for agents and categories under `"[opencode]"`.
- `omp_models.yaml` mirrors the OpenCode Codex model IDs, output limits, modalities, and pricing under `providers.codex_api.models`. The provider ID avoids OMP's built-in `codex` discovery namespace.
- The custom catalogs omit `gpt-5.4-mini` and `gpt-5.5`; no OMO agent/category or OMP model role selects them. Historical Tokscale aliases and test fixtures remain for their separate purposes.
- In OAuth mode, `pull.py` preserves the installed `provider.codex` object, so removing a model from the repository template does not prune it from an already installed OAuth config. The active OpenCode file needs a one-time cleanup or an API-mode reinstall.
- `omp_config.yml` maps `smol` and `tiny` to `gpt-6-luna`; all other OMP roles use `gpt-6-sol` with role-specific thinking levels.
- GPT-5.6 Sol and Terra roles converge on GPT-6 Sol; GPT-5.6 Luna roles move to GPT-6 Luna. Historical GPT-5.6 aliases remain in `tokscale_model_alias.json` for old usage records.
- GPT-6 Sol and Luna use the official standard prices for prompts of at most 272K input tokens. OpenCode sets `context: 400000`, `input: 272000`, and `output: 128000` for both the custom `codex` gateway and official `openai` OAuth provider. OMP retains a conservative 272K total context window because its custom-model schema has no separate input limit. Neither client's local compaction metadata is a strict per-request input guard.

## Field mapping

- `limit.context` -> `contextWindow`, except GPT-6 Sol and Luna: OMP keeps `contextWindow: 272000` to limit long-context usage without a separate input field.
- `limit.output` -> `maxTokens`
- `modalities.input` -> `input`
- `cost.input` -> `cost.input`
- `cost.output` -> `cost.output`
- `cost.cache_read` -> `cost.cacheRead`
- OMP custom-provider models set `reasoning: true`.
- When OpenCode does not declare `cost.cache_write`, set OMP `cost.cacheWrite` to `0`; do not infer a price.
- The repository disables OMP's bundled `azure` provider so only the explicitly configured `codex_api` catalog is selectable for these models.
- `pull.py` replaces the target OMP `config.yml` with `omp_config.yml`; capture intentional setup changes back into the repository before running the installer again.

## Verification

Render `baseUrl: CODEX_BASE_URL` to a literal URL in a temporary `models.yml`, copy `omp_config.yml` to `config.yml`, and run:

```bash
qa_dir="$(mktemp -d /tmp/omp-model-sync-qa.XXXXXX)"
cp omp_config.yml "$qa_dir/config.yml"
sed 's|baseUrl: CODEX_BASE_URL|baseUrl: "http://127.0.0.1:65535/v1"|' omp_models.yaml > "$qa_dir/models.yml"
PI_CODING_AGENT_DIR="$qa_dir" omp models --json | jq '{
  providers: ([.models[].provider] | unique),
  codex_api_count: ([.models[] | select(.provider == "codex_api")] | length)
}'
rm -r "$qa_dir"
```

Expected signal: OMP exits successfully with `providers` equal to `["codex_api"]` and `codex_api_count` equal to `3`. Each OMP model must match the corresponding `opencode.jsonc` model for its ID, output limit, input modalities, and costs. GPT-6 Sol and Luna intentionally retain a smaller OMP context window.
