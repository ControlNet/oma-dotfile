# OpenCode prompt cache rate investigation (2026-09-23)

## Scope and method

- OpenCode version: 1.18.32. The local SQLite database was queried read-only. Queries accessed session metadata and assistant token counters, not conversation text or credentials.
- Cache rate here means `cache.read / (input + cache.read + cache.write)`. In OpenCode V1, `tokens.input` is already adjusted to exclude cache reads and writes. Output and reasoning tokens are not part of this denominator.
- The active repository template has a custom `codex` provider using `@ai-sdk/openai` and `setCacheKey: true`. Historical sessions must be grouped by their recorded `providerID`: most of the measured sessions actually used the built-in `openai` provider, not this custom provider.
- For Codex JSONL `token_count` events, `input_tokens` includes `cached_input_tokens`, so the equivalent rate is `cached_input_tokens / input_tokens`. The last event's cumulative usage per file was used to avoid counting repeated cumulative events.

## Local measurements

The root OpenCode session created on 2026-09-19 (OpenCode **1.18.31**, built-in `openai`, `gpt-5.6-sol`) had 7,792,612 uncached input tokens and 63,607,552 cached input tokens: **89.1%**. Its 65 direct child sessions had 47,779,169 uncached and 1,051,923,712 cached input tokens: **95.7%**. Across all sessions created on 2026-09-21 and 2026-09-22, the rates were 95.0% and 93.9%, respectively; these are not identical session cohorts.

The root session had 471 assistant model calls, including eight `compaction` calls with 675,829 uncached input tokens and no cache reads. Another 31 ordinary calls returned zero cached tokens and used 4,565,873 uncached input tokens. Ten of these ordinary misses occurred less than ten minutes after the preceding assistant call, so a simple 30-minute idle-expiry explanation does not cover every miss. Together, zero-cache calls account for 5,241,702 of the root's 7,792,612 uncached input tokens (67.3%). Excluding those calls yields a 96.1% read rate for the remaining calls; this is a diagnostic decomposition, not an achievable counterfactual guarantee.

The recent OpenCode `openai/gpt-5.6-sol` cohort had 217 first assistant calls in sessions, 216 of which returned zero cached tokens. First calls consumed approximately 3.5 million uncached tokens. Later calls can also miss: 267 later calls returned zero cached tokens and consumed about 28.5 million uncached tokens. The `openai/gpt-5.6-luna` cohort had lower overall cache rate (approximately 86.4%) and many short child sessions.

Codex local JSONL files by modification day showed cumulative cache rates of 98.4% (2026-09-21, two files) and 97.1% (2026-09-22, one file). The last recorded call was 99.6% on 2026-09-21; the 2026-09-22 last-call usage was absent. Thus a displayed 99% per-call rate should not be compared directly with an OpenCode lifetime-session rate. The model/workload/session cohorts were not controlled and this is not a benchmark of the products.

## Interpretation

- OpenCode V1 uses the session ID as `promptCacheKey` for `@ai-sdk/openai` and for providers with `setCacheKey: true`; the configured custom provider already enables it. A stable key helps only where the backend uses that hint. OpenAI's current GPT-5.6-and-later documentation says cache routing is automatic and the key is not needed to optimize hit rate on those models.
- OpenCode's compaction path constructs a new single-user-message prompt from prior conversation and sends it with no system messages or tools. Its prefix differs from the normal conversation, which explains why those compaction requests are cache misses. The following continuation also starts from a rewritten context.
- Ordinary later-call misses under ten minutes are real in the recorded usage, but the local metadata cannot distinguish a changed rendered prefix, provider-side cache routing or eviction, model/backend alias routing, or inaccurate upstream usage reporting. Establishing the exact cause would require request-level cache diagnostics or privacy-conscious request fingerprints from the upstream; do not claim a specific one from these counters alone.
- A high cache rate is not a sufficient cost metric. Compare total uncached tokens, cache-write tokens, output tokens, model pricing, and wall time. `cache.write` was zero in the local OpenCode records; this may reflect the transport's usage reporting rather than proof of no backend cache writes.

## Follow-up: why successful calls average 96% instead of 99%

The root session's assistant messages consistently recorded provider `openai`, model `gpt-5.6-sol`, and variant `medium`. None of its 31 stored user messages had a per-message `system` override. Its project's `AGENTS.md` had not changed during this session. OpenCode 1.18.31 adds `Today's date` to its environment instructions, so a daily change is possible, but the first calls on subsequent dates also followed long idle gaps; those observations cannot isolate date change from cache expiry. OMO's `<omo-env>` contains timezone and locale, not a per-call timestamp, and the repository's installed `omo-env-remover` strips that block. Historical OMO package version/loading cannot be reconstructed confidently from the current package cache.

For **419 same-user-turn calls with nonzero cache reads**, grouping by character length of the immediately preceding assistant message's tool outputs gave:

| Previous tool output | Calls | Uncached input | Cached input | Cache read rate |
| --- | ---: | ---: | ---: | ---: |
| Under 5,000 characters | 190 | 426,984 | 29,531,904 | 98.6% |
| 5,000–19,999 characters | 133 | 564,081 | 19,478,656 | 97.2% |
| At least 20,000 characters | 96 | 1,504,616 | 13,107,328 | 89.7% |

Large new tool outputs account for **1.50 million** uncached input tokens in those 96 otherwise cache-hitting calls. `read` and `codegraph_codegraph_explore` contributed the largest total output lengths in the root session. The strong size relationship supports new suffix material as the main reason that cache-hitting calls average below 99%; it does not prove that every uncached token is from the immediately preceding tool result.

The **31 ordinary zero-cache calls remain a separate issue**. They used 4.57 million uncached tokens. Twenty-four occurred during the same user turn as the preceding assistant call; six ordinary misses followed a positive-cache call by less than ten minutes. Most followed less than 20,000 characters of tool output, so large tool results do not explain complete misses. OMO log labels near those short-gap misses include `context-injector` skipping injection and ordinary skill-reminder activity, but no demonstrated system-prompt mutation. The persisted database and logs do not contain the complete wire request on both sides of a miss. A request fingerprint or upstream cache diagnostics would be necessary to distinguish a changed prompt prefix from server-side cache loss.

This decomposition answers the two rate questions separately: roughly 96% on cache-hitting calls is largely expected when tools add substantial fresh context; the root session's lower lifetime rate is dominated by complete misses and compaction. Narrowing routine file reads and codegraph output may improve the former, but do not indiscriminately truncate information needed for the task. No system-prompt edit is justified by the current evidence.

## Sources

- OpenCode V1.18.32 usage accounting: https://github.com/anomalyco/opencode/blob/v1.18.32/packages/opencode/src/session/session.ts
- OpenCode V1.18.32 cache-key injection: https://github.com/anomalyco/opencode/blob/v1.18.32/packages/opencode/src/provider/transform.ts
- OpenCode V1.18.32 compaction construction: https://github.com/anomalyco/opencode/blob/v1.18.32/packages/opencode/src/session/compaction.ts
- OpenAI prompt caching documentation: https://developers.openai.com/api/docs/guides/prompt-caching
- OpenAI prompt cache diagnostics: https://developers.openai.com/api/docs/guides/prompt-caching/diagnostics
- OpenCode V1.18.31 environment prompt (date): https://github.com/anomalyco/opencode/blob/v1.18.31/packages/opencode/src/session/system.ts
- OpenCode V1.18.31 request preparation: https://github.com/anomalyco/opencode/blob/v1.18.31/packages/opencode/src/session/llm/request.ts
