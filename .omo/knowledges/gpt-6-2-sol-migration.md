# GPT-6.2 Sol migration

- On 2026-11-27, every model slot that used `gpt-6.1-sol` moved to `gpt-6.2-sol`: OMO agents
  and categories, OMP roles and model definitions (API and OAuth), and the OpenCode catalog
  entry and OAuth limit overrides that OMO's `codex/...` IDs resolve to. GPT-6 Luna and Astra
  stay the same.
- Official source: https://developers.openai.com/api/docs/models/gpt-6.2-sol. Same limits and
  prices as GPT-6.1 Sol: 1,050,000-token context (922,000 max input), 128,000 max output,
  text/image input, text output; USD per 1M tokens: input 2, cached input 0.1, cache writes 2.5
  (30-minute retention), output 10. Over 272K input tokens, input and cache rates double and
  output is 1.5x for the whole request, so the 272K input budget stays (OpenCode
  `context 400000 / input 272000 / output 128000`, OMP `contextWindow 272000`). Knowledge
  cutoff 2026-06-01. The page lists no reasoning effort levels; it only says `none` is rejected.
- Local discovery on 2026-11-27: `opencode models openai --pure` lists `openai/gpt-6.2-sol` and
  `-fast`. OMP's `~/.omp/agent/models.db` cache did not have `gpt-6.2-sol` yet; OMP takes the ID
  from `models.yml` / `models.oauth.yml`.
- Tokscale: `gpt-6.2-sol` aliases added; `gpt-6.1-sol` and `gpt-6-sol` aliases kept for history.
- As before, an installed OAuth OpenCode config keeps its own `provider.codex` object, so it
  still shows an old `codex/gpt-6-sol` entry until it is cleaned up or reinstalled in API mode.

## Verification

```bash
python3 -m unittest discover -s tests
python3 -m json.tool config/tokscale/model-aliases.json > /dev/null
git diff --check
grep -rn 'gpt-6\.1-sol' config | grep -v tokscale   # expect no output
```
