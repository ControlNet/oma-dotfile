# OpenCode V2 compatibility audit (2026-09-23)

The local `opencode` binary is 1.18.32. The separately published `@opencode/cli` npm package reports `latest: 2.0.14`. These are distinct release channels; the V1 GitHub release page still marks 1.18.32 as latest.

## Repository findings

- `opencode.jsonc` uses the V1 `plugin` and `provider` keys and V1 nested provider/model shapes. V2's migration guide says supported V1 server configuration is normalized in memory, so this is not by itself a blocker. The model-level `reasoning` boolean is listed as accepted but unsupported in V2.
- The three configured package plugins have V2 problems. The OMO maintainer says its existing V1 plugin does not load in V2 (issue #8548, duplicate of #7847). `opencode-wakatime` has an open V2 support request (#85). `opencode-openai-codex-auth` currently exports a V1 `Plugin` function returning `auth` and depends on `@opencode-ai/plugin` 1.x, so its current source is incompatible with the V2 entrypoint contract.
- Both local files in `plugins/` are V1 entrypoints. `omo-env-remover.js` returns `experimental.chat.system.transform`. `gotify-notify.js` returns V1 `event`, `permission.ask`, and `tool.execute.before` hooks and uses the V1 SDK client shape. Both need real ports; changing config keys or paths alone cannot make them run.
- `tui.json` uses V1 `variant_cycle`. V2 uses one global `cli.json` and command ID `variant.cycle` (default `ctrl+t`). V2 auto-migrates supported global TUI settings only on first startup when `cli.json` is absent. The installer continues to install `tui.json` and does not maintain `cli.json`, so subsequent V2 installs cannot enforce the intended `ctrl+y` binding.
- `omo.jsonc` is plugin-owned. Its model and agent settings cannot be validated in V2 until OMO itself supports V2. `skills/` and installed `AGENTS.md` are expected to remain discoverable in V2.
- `pull.py` detects only the presence of `opencode`, not its major version. It therefore installs the V1 plugin set and TUI config even on V2. Its OAuth rendering retains the V1 provider shape (which V2 normalizes), but V2-specific installation needs separate handling before migration.

## Source references

- https://opencode.ai/v2/docs/migrate-v1
- https://opencode.ai/v2/docs/build/plugins/migrate-v1
- https://opencode.ai/v2/docs/cli/config
- https://opencode.ai/v2/docs/cli/keybinds
- https://github.com/code-yeongyu/oh-my-openagent/issues/8548
- https://github.com/angristan/opencode-wakatime/issues/85
- https://github.com/numman-ali/opencode-openai-codex-auth/blob/main/index.ts

No V2 binary was installed or run during this audit. Compatibility conclusions for local and package plugins are from source and upstream documentation/issues, not runtime smoke tests.

## Staying on V1

As of 2026-09-23, `https://opencode.ai/install` is the V1 installer and supports `--version <version>` (or `VERSION`). Its unpinned path resolves `anomalyco/opencode` GitHub `releases/latest`, currently `v1.18.32`. The V2 installer is `https://opencode.ai/v2/install`. To avoid an unpinned channel change, use `curl -fsSL https://opencode.ai/install | bash -s -- --version 1.18.32` for this exact V1 release. Check `opencode --version` afterward. For future V1 updates, query GitHub releases and reject tags that do not start with `v1.` before invoking the installer.

Source: https://github.com/anomalyco/opencode/blob/dev/install
