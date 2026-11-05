# Tokscale "cost totals may be incomplete" and Codex rollout warnings (checked 2026-11-05, tokscale 4.20.0)

Tokscale prints two warnings on most runs. Neither means the scanner or autosubmit is broken.

## "some usage is partial, unpriced, or has stale pricing"

`tokscale pricing explain --json --no-spinner` prints one row per usage record. The output is large
(about 150 MB for ~250k rows), so redirect it to a file and aggregate it rather than reading it raw.
Each row has the fields `estimateStatus`, `coverage`, `priceSource`, `matchedModelId` and `uncoveredBuckets`.

| `estimateStatus` | Meaning |
| --- | --- |
| `Authoritative` | The client recorded the cost itself (`priceSource: ProviderReported`). |
| `CurrentEstimate` | Priced with today's LiteLLM / OpenRouter / Models.dev rates. These rows are the "stale pricing" part: old usage priced at current rates. Coverage is complete. |
| `PartialEstimate` (`coverage: false`) | Some token buckets have no rate, so the cost is a lower bound. |

On this setup the `PartialEstimate` rows are all legacy models and come to about $42 out of about
$50k in total:

- `github_copilot/claude-opus-4.5`, `github_copilot/claude-sonnet-4.5`, `github_copilot/grok-code-fast-1`
  (grok has no `cache_read` rate).
- `azure/gpt-5.2-codex`, matched to `azure/eu/gpt-5.2-codex`.
- `opencode/union-alpha`, which LiteLLM wrongly matches to the image model
  `fireworks_ai/.../flux-1-dev-controlnet-union`. Its cost is effectively zero; this is a fuzzy-match
  mistake, not a real price.

Aggregate the output like this:

```bash
tokscale pricing explain --json --no-spinner > pricing.json 2>/dev/null
python3 -I - pricing.json <<'EOF'
import json, sys, collections as C
rows = json.load(open(sys.argv[1]))
print(C.Counter((r["estimateStatus"], r["coverage"], r["priceSource"]) for r in rows).most_common())
part = C.Counter((r["client"], r["providerId"], r["modelId"], r.get("matchedModelId"))
                 for r in rows if r["estimateStatus"] == "PartialEstimate")
for k, v in part.most_common(): print(v, k)
EOF
```

## "N of M inspected rollout files contain Codex activity but no supported usage records"

These are Codex rollouts under `~/.codex/sessions` that have no `event_msg` with
`payload.type == "token_count"` and a non-null `info`. In 4.20.0 the count includes:

- Sessions that were opened and closed before the first turn. They contain only `session_meta` plus
  the injected AGENTS.md / `<environment_context>` / permissions messages, with no `turn_context`.
  No model call happened, so no tokens are missing.
- Turns that were interrupted (`turn_aborted`, `reason: interrupted`) before Codex emitted a
  `token_count`. Any tokens such a turn used are lost; Codex never wrote them down.

Rollouts that contain only `session_meta` + `thread_settings_applied` are not counted as "activity".
The warning covers every scanned file regardless of the report date range, so it keeps appearing
until those files are removed or moved out of the sessions tree. It cannot be fixed on the tokscale side.

To list the files:

```bash
python3 -I - <<'EOF'
import json, glob, os
for f in sorted(glob.glob(os.path.expanduser("~/.codex/sessions/**/rollout-*.jsonl"), recursive=True)):
    usage = 0
    for line in open(f, errors="replace"):
        try: o = json.loads(line)
        except ValueError: continue
        p = o.get("payload") or {}
        usage += p.get("type") == "token_count" and bool(p.get("info"))
    if not usage: print(f)
EOF
```

Expected result: this script lists a couple more files than tokscale counts, because it also lists the
`session_meta` + `thread_settings_applied` files that tokscale ignores.
