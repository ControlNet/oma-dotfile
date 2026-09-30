# OMO Native 5.0.1 support audit

Audited on 2026-09-28 against the stable npm release `omo-ai@5.0.1` (engine
`@code-yeongyu/senpi@2026.9.27`), unpacked with `npm pack`. The locally installed
`omo-ai 5.0.0-0.beta.90` was deliberately not used as the reference.

## Layout

- State dir: `~/.omo/agent` (override: `OMO_CODING_AGENT_DIR`, then `SENPI_CODING_AGENT_DIR`,
  then `PI_CODING_AGENT_DIR`; `bin/lib/agent-dir.js`). Senpi docs say `~/.senpi/agent`; omo rebrands it.
- `~/.omo/omo.jsonc` is shared with the OpenCode plugin. Native reads shared top-level keys, then
  `"[senpi]"` (legacy, auto-renamed), then `"[native]"`. `"[opencode]"` is opaque to native.
- Unknown top-level keys (e.g. `claude_code`, `team_mode`) are stripped with a diagnostic, and any
  diagnostic also disables PostHog telemetry. Keep OpenCode-only keys inside `"[opencode]"`.
- Native agents: `explore, librarian, plan-consultant, plan-reviewer, omo-native-code-reviewer,
  omo-native-gate-reviewer, omo-native-qa-executor`. There is no sisyphus/hephaestus/oracle/etc.
  An unknown agent name under shared `agents` becomes a promptless agent.
- Native categories: the OpenCode set plus `architect`. Since 5.0.1, the built-in `writing`
  default is Claude-only, so pin it when there is no Claude login.
- Model ids are `provider/model` with engine provider ids. ChatGPT OAuth is
  `chatgpt-subscription` (`/login chatgpt-subscription`). `openai-codex/` gets migrated to it.
- Custom providers: `~/.omo/agent/models.json`, with `api: openai-responses`.
  - `apiKey` and `headers` accept `$VAR`/`${VAR}`. `baseUrl` is sent verbatim, so it must be a literal.
  - The engine writes `models.json` back as plain JSON, which drops comments.
- `settings.json`: `defaultProvider`/`defaultModel`/`defaultThinkingLevel` plus many runtime-mutated
  keys (`tipsHistory`, `changelogSeen`, `modelThinkingLevels`). Installers must merge, not overwrite.
  Do not add the omo plugin to `packages`, because the launcher injects it.
- Context files:
  - Global `~/.omo/agent/AGENTS.md`.
  - The default-on builtin `rules` extension also injects the first of `~/.config/opencode/AGENTS.md`
    or `~/.claude/CLAUDE.md`, plus every file in `~/.claude/rules`, `~/.omo/rules`, `~/.opencode/rules`
    and `~/.pi/rules`.
  - The same text in several of those places can therefore be injected more than once.
- Skills: `~/.omo/agent/skills/` and `~/.agents/skills/`. `~/.claude/skills` is not scanned by
  default. SKILL.md needs `name` and `description`. The user root beats bundled plugin skills.
- Extensions:
  - `~/.omo/agent/extensions/*.js` are auto-discovered, using the same `export default (pi) => {}`
    API as oh-my-pi.
  - `agent_end` has `willRetry`/`aborted` and no `willContinue`.
  - The question tool is `ask_user_question` or `request_user_input`, not `ask`.
  - Permission prompts arrive on `pi.events.on("permission_asked")`.
- Sessions:
  - Main sessions: `~/.omo/agent/sessions/--<cwd>--/*.jsonl` (v3). Assistant messages carry separate
    `provider`/`model` fields and `usage` with a cost.
  - Delegated tasks: `<project>/.omo/senpi-task/sessions/`.
- `omo setup --yes` imports OpenCode API keys, MCP, skills, custom providers with a literal baseURL,
  and model choices. It never imports AGENTS.md or OAuth tokens, and it only runs when invoked.
- Telemetry off: `"telemetry": {"enabled": false}` in omo.jsonc, or `OMO_DISABLE_POSTHOG=1`/`DO_NOT_TRACK=1`.
  Engine install ping: `enableInstallTelemetry: false` or `PI_TELEMETRY=0`.

## Impact on this repo

- `pull.py` currently gates OMO config on the `opencode` executable, which assumes OMO is only an
  OpenCode plugin. That assumption no longer holds.
- `install_omo_config --oauth` rewrites `codex/` to `openai/`, which is correct for OpenCode but not
  for native (`chatgpt-subscription/`).
- `omp-gotify-notify.js` needs the event and tool-name fixes above before reuse.

## 5.1.0 delta (checked 2026-09-29, engine senpi 2026.9.28-7)

- The earlier conclusions still hold:
  - The native agent list, the `rules` builtin id and its `~/.claude` sources are unchanged.
  - `telemetry: {enabled}` in omo.jsonc and `OMO_DISABLE_POSTHOG` still control PostHog.
- The install now lives in the Bun global tree (`~/.bun/install/global/node_modules/omo-ai`).
  `~/.bun/bin/omo` is a generated sh shim. `pull.py` already searches `~/.bun/bin`.
- New experimental computer use is on by default on supported hosts; X11 is supported on Linux.
  omo.jsonc has a `computer` key, and the changelog says `computer.enabled: false` removes it.
- New `models discover <provider>` fills an OpenAI-compatible provider's models in `models.json`
  from its `/models` endpoint.
- `task.residency_max_children` now defaults to `"unlimited"`.
- Memory can make extra model calls for very long entries.
- The `[native]` block written by `omo setup` survived the upgrade unchanged.

## Verifying generated config against a real omo (2026-09-29)

- Headless modes (`-p`, `--mode json`) never print omo.jsonc diagnostics. Start the TUI in a
  detached tmux session and capture the pane instead.
  - A bad key shows `OmO Native: configuration diagnostics: Ignored unknown keys in ...`.
  - Always run a control config containing a deliberately unknown key; that proves the check can fail.
- Isolate everything:
  - Use a scratch `HOME` for both `~/.omo/omo.jsonc` and `~/.omo/agent`.
  - Use `env -i HOME=... PATH=... TERM=...`, so inherited provider keys (e.g. `AZURE_OPENAI_API_KEY`)
    cannot reach a real model.
  - Pass `--omo-senpi-onboarding-disabled`. On a fresh home, onboarding starts a model turn by itself,
    and this once spent real Azure credit.
- Checking the rules switch:
  - With the rules builtin loaded, `/rules` prints `pi-rules: N rules from M sources` (it read
    `~/.claude/rules`).
  - With `disabledBuiltinExtensions: ["rules"]`, the `/rules` command does not exist.
- `omo --offline --list-models` lists the generated `codex` gateway models. Without auth they load
  but are listed as unavailable, so set a dummy `CODEX_API_TOKEN` to see them.

## Tokscale and OMO Native usage (checked 2026-09-29, Tokscale 4.17.0)

- Tokscale's `senpi` client ("Senpi (OmO Native)") reads `$SENPI_CODING_AGENT_DIR/sessions`, which
  defaults to `~/.senpi/agent`. Branded omo writes `~/.omo/agent/sessions`, so by default Tokscale
  counts nothing.
- Subagent (task child) discovery already exists upstream:
  - It reads each main session's header `cwd` and scans `<cwd>/.omo/senpi-task/children`.
  - It honors `task.state_dir` from project/user `omo.jsonc`.
  - Sources: junhoyeo/tokscale PRs #1113, #1248, #1255.
- Discovery runs only over the senpi agent dir. `TOKSCALE_EXTRA_DIRS=senpi:...` and
  `scanner.extraScanPaths` add plain scan roots without child discovery, and globs are not expanded.
- Verified run: `SENPI_CODING_AGENT_DIR=~/.omo/agent bunx tokscale@latest -c senpi`, launched from `~`.
  - It counted 24 messages / 511,834 tokens.
  - That exactly matches a direct parse: main 23 / 508,000 plus child 1 / 3,834.
  - The parent session does not duplicate child usage.
- No upstream issue asked for the `~/.omo/agent` default as of 2026-09-29. The related omo issue is
  #6717, about `~/.senpi` vs branded dirs.
- Reported upstream as junhoyeo/tokscale#1375 (2026-09-29).
