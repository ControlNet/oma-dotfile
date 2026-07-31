# OMP model synchronization

## Source of truth

- `opencode.jsonc` defines the complete `provider.codex.models` catalog, including model IDs, display names, context/output limits, modalities, and costs.
- `oh-my-openagent.jsonc` defines the intended model tier allocation for agents and categories.
- `omp_models.yaml` mirrors the OpenCode Codex model catalog under `providers.codex-api.models`, but pricing must be checked against the official OpenAI API pricing page rather than copied from OpenCode configuration.
- `omp_config.yml` maps OMP roles to the same tier allocation: `gpt-5.6-luna` for lightweight work and `gpt-5.6-sol` for default, planning, slow, and designer work.

## Field mapping

- `limit.context` -> `contextWindow`
- `limit.output` -> `maxTokens`
- `modalities.input` -> `input`
- `cost.cache_read` -> `cost.cacheRead`
- OMP custom-provider models set `reasoning: true`.
- GPT-5.6 standard short-context pricing includes cache writes at 1.25 times the uncached input price: Luna `0.25`, Terra `2.5`, and Sol `6.25` USD per million tokens.
- OMP 15.9.1 accepts and calculates `cost.cacheWrite`, but its OpenAI Responses usage parser currently emits `cacheWrite: 0`; the configured write price is therefore correct metadata but is not reflected in observed Responses API cost totals until OMP parses OpenAI cache-write usage.

## Verification

Render `baseUrl: CODEX_BASE_URL` to a literal URL in a temporary `models.yml`, copy `omp_config.yml` to `config.yml`, and run:

```bash
qa_dir="$(mktemp -d /tmp/omp-model-sync-qa.XXXXXX)"
cp omp_config.yml "$qa_dir/config.yml"
sed 's|baseUrl: CODEX_BASE_URL|baseUrl: "http://127.0.0.1:65535"|' omp_models.yaml > "$qa_dir/models.yml"
PI_CODING_AGENT_DIR="$qa_dir" omp --list-models codex-api
```

Expected signal: OMP exits successfully and lists every Codex model from `opencode.jsonc` under the `codex-api` provider with matching context and max-output limits.
