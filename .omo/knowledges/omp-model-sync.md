# OMP model synchronization

## Source of truth

- `opencode.jsonc` defines the complete `provider.codex.models` catalog, including model IDs, display names, context/output limits, modalities, and costs.
- `omo.jsonc` defines the intended OpenCode model tier allocation for agents and categories under `"[opencode]"`.
- `omp_models.yaml` mirrors the OpenCode Codex model catalog under `providers.codex_api.models`, including pricing. The provider ID avoids OMP's built-in `codex` discovery namespace.
- `omp_config.yml` maps `smol` and `tiny` to `gpt-5.6-luna`; all other OMP roles use `gpt-5.6-sol` with role-specific thinking levels.

## Field mapping

- `limit.context` -> `contextWindow`
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

Expected signal: OMP exits successfully with `providers` equal to `["codex_api"]` and `codex_api_count` equal to `6`. The models must match `opencode.jsonc` for IDs, names, context/output limits, input modalities, and costs.
