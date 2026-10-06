# OMP WakaTime options (checked 2026-10-07, OMP 18.2.5, wakatime-cli v2.26.15)

The repo installs WakaTime for OpenCode (`opencode-wakatime`), Codex
(`codex-cli-wakatime`) and Claude Code (`claude-code-wakatime`). OMP has no
dedicated installer step.

## Key finding: wakatime-cli parses OMP transcripts natively

- `wakatime-cli` has a built-in OMP parser (`pkg/ai/omp.go`, added in commit
  351d1dd8ce on 2026-08-07, first stable release **v2.24.0**). It reads
  `~/.omp/agent/sessions/**/*.jsonl` (upstream pi uses `pkg/ai/pi.go`,
  `~/.pi/agent/sessions`).
- The transcript parsers run whenever `wakatime-cli` sends any heartbeat,
  unless `--sync-ai-disabled` is passed. `--sync-ai-activity` runs them on demand
  without `--entity`. There is no per-parser filter flag.
- A process-wide lock (`wakatime-ai-sync-*`, 100 ms timeout) skips concurrent
  syncs. Progress is stored in `~/.wakatime/ai-timestamps/`.
- Verified locally: an isolated `WAKATIME_HOME` with `api_url` pointing to a
  local fake server, then `wakatime-cli --sync-ai-activity`. It produced
  198 OMP heartbeats (user agent suffix `OMP`, category `ai coding`) from the
  OMP sessions of 2026-08-31..09-03, with file entities, language, branch, model,
  input/output/cached tokens and `ai_line_changes`. Other harnesses in the same run:
  codex-cli, opencode-cli, claude-code, codex-vscode, codex-exec.
- Consequence: on a machine where another WakaTime integration runs
  wakatime-cli (Codex/Claude/OpenCode plugin, editor), OMP activity is already
  reported. Gaps: reporting is delayed until the next wakatime-cli run, and a
  host that runs only OMP never triggers the parser.
- The user's heartbeats go to a self-hosted WakaTime-compatible server
  (`api_url` in `~/.wakatime.cfg`), not wakatime.com.

## Third-party OMP/pi extensions (send their own heartbeats)

| Package / repo | Target | Notes |
|---|---|---|
| `omp-wakatime` (npm 0.2.0, VxxxlBxxxxv) | OMP | session/tool_result/shutdown, file heartbeats, passes `--sync-ai-disabled` |
| `wakatime-omp` (ephraimduncan, GitHub only) | OMP | single .ts file, modeled on claude-code-wakatime |
| `wakatime-pi` (aliulei, GitHub only) | OMP | `turn_end` token heartbeats via `--extra-heartbeats` |
| `omp-wakapi` (npm 0.2.0, syrex1013) | OMP + Wakapi | own HTTP heartbeats |
| `pi-wakatime` (npm 1.1.3, ttttmr) | upstream pi | `"pi"` manifest; OMP bundle has no `pi.extensions` string, so OMP loading is unverified |
| `@chronova/pi-plugin`, `@arcat/ziit-pi` | OMP | Chronova / Ziit backends, not WakaTime |

Not listed on wakatime.com/plugins, awesome-pi.site or pi.dev/packages.
Combining a heartbeat extension with the native transcript parser risks
double-counting AI line changes, because both report the same edits.

## Recommended approach

Rely on the native parser and only add a trigger: a small OMP extension that
runs `wakatime-cli --sync-ai-activity` detached, rate-limited after turns and
once on `session_shutdown`. It should use an existing CLI (`~/.wakatime/wakatime-cli*`
or PATH) and never download one.

## Implemented: omp-wakatime-sync.js (2026-10-07)

- Installed by `pull.py` into `~/.omp/agent/extensions/` next to the Gotify notifier.
- `agent_end` (skipped when `willContinue`) runs `wakatime-cli --sync-ai-activity`
  detached, at most every `OMP_WAKATIME_SYNC_INTERVAL_SEC` (default 120).
  `session_shutdown` always runs it.
- CLI lookup order: `OMP_WAKATIME_CLI`; `$WAKATIME_HOME/.wakatime/` and
  `~/.wakatime/` (`wakatime-cli`, `wakatime-cli-<os>-<arch>`); `PATH`. A missing
  CLI is logged once (`sync_skip no_cli`) and the extension never downloads one.
- Log file: `~/.omp/logs/wakatime-sync.log`. Disable with `OMP_WAKATIME_SYNC=false`.
- Tests: `node --test tests/omp-wakatime-sync.test.mjs` uses a shell-script fake CLI.
- Real OMP 18.2.5 check: `omp models --json --no-extensions -e ./omp-wakatime-sync.js`
  with a fake `OMP_WAKATIME_CLI` loads the extension, fires `session_shutdown`, and
  spawns the CLI with `--sync-ai-activity`. The `agent_end` path still needs a real
  session with model credentials to verify.

## OMO Native (checked 2026-10-07, omo 5.1.21, engine senpi 2026.10.10-3)

- Extension side is compatible: senpi has `agent_end` and `session_shutdown`
  (`dist/core/extensions/types.d.ts`), and OMO Native auto-loads
  `~/.omo/agent/extensions/`. Difference: senpi's `AgentEndEvent` has
  `willRetry` / `aborted`, not OMP's `willContinue`.
- Blocker: wakatime-cli (develop @ 7076d88, 2026-10-05) has no OMO parser. Pi reads
  the hardcoded `~/.pi/agent/sessions` with no env override; OMP reads
  `~/.omp/agent/sessions`. Nothing reads `~/.omo`. No upstream issue or PR
  mentions OMO, oh-my-openagent or senpi.
- OMO session files use the same pi v3 JSONL layout (`{"type":"session","version":3,...}`,
  `message.role` assistant/toolResult, `usage.input/output/cacheRead`), so an
  `omo.go` cloned from `omp.go` (generic provider over `~/.omo/agent/sessions`)
  would likely work. The OMP parser was added by the maintainer in a batch commit
  ("Add more ai parsers", 351d1dd8ce).
- Go 1.25.5 is available locally (`~/.go/bin/go`) to prototype such a parser.

## Installer hooks

- `omp plugin install <pkg>` / `omp install`; `omp plugin list --json` returns
  `{"npm": [...], "marketplace": [...]}`. `omp plugin marketplace list` is empty
  by default.
- OMP auto-loads `~/.omp/agent/extensions/*`; `pull.py` already installs
  `omp-gotify-notify.js` there.
