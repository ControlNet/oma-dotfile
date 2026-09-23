# OMO reasoning and OpenCode V1 variants

## OMO 5.0 beta update (2026-09-23)

With `oh-my-openagent@beta` resolved to `5.0.0-beta.84`, OMO itself supplies the native agent variant. A test with an isolated `XDG_CONFIG_HOME` and no local reasoning plugin returned Sisyphus `high`, librarian `xhigh`, Atlas `medium`, and oracle `high`. The same Sisyphus result appeared with the local plugin installed. Therefore the temporary `omo-reasoning-variant.js` plugin was redundant and was removed from the repository and the active OpenCode plugin directory. OpenCode V1's TUI still shows `Default` on agent switch because its model variant state is separate from agent configuration.

The findings below document the earlier OMO 4.19.4 behavior for comparison.

On OpenCode 1.18.32 with oh-my-openagent 4.19.4, the unified OMO setting `[opencode].agents.sisyphus.reasoning: "high"` generates an OpenCode agent config with `reasoning: "high"` but no native `variant`. `opencode debug agent 'Sisyphus - ultraworker'` reported `variant` absent, and the TUI selected `Default`.

OMO's V1 plugin `applyAgentVariant()` runs from its `chat.params` hook. OpenCode's `session/llm/request.ts` computes variant-derived request options before calling that hook, so this mutation cannot reliably select the request variant. OpenCode's prompt path does honor `agent.variant` before creating the user message. A later `config` hook can map the OMO-generated agent `reasoning` value to `agent.variant`; installed local plugins load after configured package plugins. The temporary local plugin used that approach while preserving an explicit variant.

The previous local plugin was verified with a temporary `OPENCODE_CONFIG_DIR`: `opencode debug agent 'Sisyphus - ultraworker'` reported `variant: high`, model `openai/gpt-6-sol`. That plugin is no longer part of this repository.

## TUI display limitation

OpenCode 1.18.32's TUI stores variant selections per model in its private `modelStore.variant` state (`packages/tui/src/context/local.tsx`). Switching an agent updates only `agentStore.current`. The variant picker reads the private per-model state and shows `Default` when it is unset; it does not read `agent.variant`. The TUI plugin API does not expose a setter for that state or an agent-switch event. The server prompt path selects `ag.variant` when the request has no explicit variant and the selected model matches the agent model, so `Default` in the TUI does not prove the request uses medium. A user-selected per-model variant takes precedence and may affect other agents using that model.

Source: https://github.com/anomalyco/opencode/blob/v1.18.32/packages/tui/src/context/local.tsx
Source: https://github.com/anomalyco/opencode/blob/v1.18.32/packages/tui/src/component/dialog-variant.tsx

Source: https://github.com/anomalyco/opencode/blob/v1.18.32/packages/opencode/src/session/llm/request.ts
Source: https://github.com/anomalyco/opencode/blob/v1.18.32/packages/opencode/src/session/prompt.ts
