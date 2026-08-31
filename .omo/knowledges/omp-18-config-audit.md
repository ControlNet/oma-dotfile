# OMP 18 configuration audit

Audited against local `omp/18.0.11` and upstream tag `v18.0.11` on
2026-08-31.

## Repository template status

- `omp_config.yml` now mirrors the OMP 18 setup-generated configuration and no
  longer contains the audited legacy keys.
- The repository template includes `setupVersion: 2`, the complete OMP 18 model
  role set, and the selected TUI, display, status-line, interaction, memory, and
  editing settings.
- `gpt-5.6-luna` serves the lightweight `smol` and `tiny` roles;
  `gpt-5.6-sol` serves the remaining roles with role-specific thinking levels.

## Model metadata

- `omp_models.yaml` is valid under OMP 18 and the `codex_api` provider loads.
- `codex` cannot be used as the custom provider ID because OMP uses that ID
  for built-in Codex configuration discovery, skills, session import, and web
  search. `codex_api` avoids that namespace collision.
- Custom models replace bundled entries with the same provider/model identity.
  The repository currently fixes GPT-5.6 Luna/Terra/Sol at a 272000 context
  window, while OMP 18.0.11's bundled catalog reports 1050000 for those model
  IDs under its built-in Azure catalog.
- Official OpenAI API model and pricing pages do not publicly document the
  `gpt-5.6-luna`, `gpt-5.6-terra`, and `gpt-5.6-sol` endpoints. Do not copy the
  bundled 1050000 value blindly; confirm limits and pricing against the actual
  `CODEX_BASE_URL` gateway contract.
- OMP 18.0.11 includes an `azure` provider in its bundled model catalog even
  when the repository defines no Azure provider. `omp_config.yml` explicitly
  disables it so it does not appear in the selectable model set.
- The current full custom-provider catalog is intentionally duplicated from
  `opencode.jsonc`. This requires manual synchronization whenever model limits,
  prices, or IDs change. A future improvement is to generate the OMP model list
  from one canonical catalog or reduce `models.yml` to provider overrides when
  the gateway can expose model discovery.

## Gotify extension

- `omp-gotify-notify.js` parses and loads successfully under OMP 18.0.11.
- The registered events (`agent_end`, `tool_call`, and `auto_retry_end`) remain
  part of the current extension API.
- OMP 18's `AgentEndEvent` exposes `willContinue` when an automatic
  continuation or retry is already scheduled. The current `agent_end` handler
  does not check it, so it can send an "Agent turn completed" notification
  before the overall run is actually terminal. Return early when
  `event?.willContinue` is true.
- The extension intentionally swallows delivery and summarizer failures and has
  no diagnostic log, unlike the OpenCode and Codex notifiers. Troubleshooting a
  missing OMP notification therefore has no local evidence. A bounded,
  redacted diagnostic log is a worthwhile follow-up.
- The OMP summarizer lacks the Google AI Studio direct `generateContent`
  fallback already implemented in the OpenCode and Codex notifiers. If the
  shared summarizer endpoint is Google-compatible and `/chat/completions`
  returns 500, OMP falls through to `/responses` and then the preview without
  the working Google fallback.

## Verification commands

```bash
omp --version
node --check omp-gotify-notify.js
omp models --json -e ./omp-gotify-notify.js | jq \
  '[.models[] | select(.provider == "codex_api") | {selector, contextWindow, maxTokens, thinking, cost}]'
omp config list --json
git diff --check
```
