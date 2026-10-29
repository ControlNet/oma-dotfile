# Using Hindsight memory with OMO Native (omo 5.1.0 / senpi)

Status as of 2026-09-30: researched from sources only; not verified end-to-end.

## Why it can work

- Hindsight's pi integration (`vectorize-io/hindsight`,
  `hindsight-integrations/coding-agents/src/harness/pi-extension.ts`) is a pi extension using
  `pi.on("before_agent_start")` (recall + system prompt injection), `pi.on("agent_end")`
  (transcript retain), and `pi.registerTool` (memory tools).
- senpi (the engine under omo) documents the same three APIs in
  `@code-yeongyu/senpi/docs/extensions.md` and loads extra extensions from the `extensions`
  array of its `settings.json`.
- omo's senpi agent dir is `~/.omo/agent/` (not `~/.pi/agent/`), so settings live in
  `~/.omo/agent/settings.json` and auto-discovered extensions in `~/.omo/agent/extensions/`.

## Gap

- `npx @vectorize-io/hindsight-coding-agents install pi` hardcodes `~/.pi/agent/settings.json`
  (`piFamilyInstaller("pi", [".pi", "agent"])`); it does not know about `~/.omo/agent`.
- The registered entry is `<pkgRoot>/dist/pi.js`; with `npx` the pkgRoot is an npm cache path,
  so install the package globally before registering the path.
- Workaround: run the pi install, then copy the same absolute entry into
  `~/.omo/agent/settings.json` `extensions`.

## Interaction with omo built-in memory

- Built-in memory can be disabled with `memory.enabled: false` in `~/.omo/omo.jsonc`.
  Running both injects two memory systems into the prompt and runs two background writers.

## Cross-machine behavior

- Hindsight bank id defaults to `coding-agent::{gitProject}` where gitProject is the main
  worktree basename, so it is path-independent (unlike omo's path hash, see
  [[omo-memory-architecture]]). Same-named repos share a bank unless `mapPathToBank` is set.
- Sync only works with a shared server: Hindsight Cloud or a self-hosted server reachable
  from all machines. `--server daemon` is a per-machine local store.
- Client config: `~/.hindsight/coding-agent.json`; token via `HINDSIGHT_API_TOKEN` env.
