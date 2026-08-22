# OMO unified configuration

- Current user config: `~/.omo/omo.jsonc`.
- Project overrides: `.omo/omo.jsonc`, merged from ancestor directories toward the current project.
- OpenCode-only OMO settings belong under `"[opencode]"` in `omo.jsonc`.
- `oh-my-openagent.json[c]` and `oh-my-opencode.json[c]` are migration inputs, not active runtime config files.
- `~/.omo/config.json[c]` is also obsolete and should be retired after `omo.jsonc` is installed.
- The repository installer must keep OpenCode core config in `~/.config/opencode/opencode.jsonc` and install OMO config separately.
- Canonical schema: `https://raw.githubusercontent.com/code-yeongyu/oh-my-openagent/dev/assets/omo.schema.json`.
- Agent model options use `reasoning`; the old `variant` field is deprecated.
