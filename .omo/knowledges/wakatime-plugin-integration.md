# WakaTime Plugin Integration Notes

Investigated on 2026-09-18.

## Confirmed behavior

- The local Codex CLI is version `0.155.0` and supports:
  - `codex plugin marketplace add/list/upgrade/remove`
  - `codex plugin add/list/remove`
  - JSON output for marketplace and plugin inspection and installation results.
- The WakaTime plugin documents this installation flow:

  ```text
  codex plugin marketplace add wakatime/codex-cli-wakatime
  codex plugin add codex-cli-wakatime@wakatime
  ```

- The plugin installs and updates `wakatime-cli` under `~/.wakatime/`, reads
  standard WakaTime settings from `~/.wakatime.cfg`, and writes its log to
  `~/.wakatime/codex-cli.log`.
- Codex plugin installation is managed state. Do not copy the plugin source into
  this repository or hand-edit Codex marketplace/plugin entries.

## Implemented pull.py integration

Implemented on 2026-09-18 as `ensure_codex_wakatime_plugin`, step `[8/10]` of
`main`, with tests in `tests/test_codex_wakatime_plugin.py`.

- Installation is unconditional, not behind a flag. Decided by the user: this
  repository is a personal dotfile installer, every other step is unconditional,
  and WakaTime is wanted on every machine. Missing prerequisites degrade to a
  warning instead of an opt-in switch.
- Run the plugin setup after `ensure_codex_config`, because both operations may
  update Codex-managed state in `config.toml`. Verified: the Codex CLI only
  appends `[marketplaces.wakatime]` and `[plugins."..."]`, preserving existing
  sections, comments, and indentation, so the line-based editor in
  `ensure_codex_config` and the CLI do not conflict as long as they run
  sequentially.
- Verified non-interactive: with `stdin` closed, both commands succeed despite
  `authPolicy: ON_INSTALL`, are idempotent (`alreadyAdded: true`, exit code 0),
  and print JSON on stdout with warnings on stderr.
- `codex plugin list --marketplace wakatime --json` exits 0 with empty arrays
  when the marketplace is absent, so the pre-check needs no special casing.
- Set `CODEX_HOME` in the child process environment to `get_codex_dir()` so the
  plugin commands honor the installer's `CODEX_DIR` and `CODEX_HOME` overrides.
- Inspect `codex plugin marketplace list --json` before adding the marketplace.
  If the configured `wakatime` source is absent, add it; if the name exists
  with a different source, warn instead of replacing it automatically.
- Inspect `codex plugin list --json --marketplace wakatime` before installing the
  plugin. Treat an installed and enabled plugin as already configured.
- Run the commands with argument arrays, capture output, avoid printing command
  output that could contain credentials, and report failures without breaking
  unrelated configuration installation.
- Do not create or rewrite `~/.wakatime.cfg` from `pull.py`; the WakaTime API key
  belongs in the user's local configuration and must never enter the repository.

## Verification strategy

- Unit-test command construction, `CODEX_HOME` propagation, JSON parsing, and
  idempotent skip behavior with mocked subprocess calls.
- Keep live marketplace installation out of the standard test suite.
- After installation, Codex must be restarted or a new session must be opened
  before the newly installed plugin is expected to load.

References:

- https://learn.chatgpt.com/docs/plugins
- https://github.com/wakatime/codex-cli-wakatime/blob/main/README.md
- https://github.com/openai/codex/blob/main/codex-rs/cli/src/plugin_cmd.rs

## Claude Code CLI behavior (investigated 2026-09-18)

- `claude plugin marketplace add wakatime/claude-code-wakatime` and
  `claude plugin install claude-code-wakatime@wakatime` are non-interactive with
  `stdin` closed, and idempotent (`already on disk`, `already installed`, exit 0).
- `CLAUDE_CONFIG_DIR` is honored by both commands.
- `claude plugin install` supports `--json`; `claude plugin marketplace add` does
  **not**, so only its exit code can be checked.
- `claude plugin list --json` and `claude plugin marketplace list --json` return
  JSON arrays, unlike the Codex equivalents which return objects.
- `marketplace list --json` reports either `{"source":"github","repo":...}` or
  `{"source":"git","url":...}` depending on how the marketplace was added, so the
  identity check must accept both.
- Marketplace and plugin state lands in `settings.json` under
  `extraKnownMarketplaces` and `enabledPlugins`, merged into the existing file.
  Verified that unrelated keys (`hooks`, `model`) survive. The CLI does rewrite
  the file, and it normalized a `model` value while saving.
- Do not pass `-y` to `claude plugin install`: it would accept a
  marketplace-declared install command unattended.
- Plugin hooks live in the plugin's own `hooks/hooks.json` and run
  `${CLAUDE_PLUGIN_ROOT}/scripts/run`, which requires `node` (or `NODE_BIN`).
  Claude Code must be restarted to load them.

## Codex marketplace state is not only in config.toml

Hand-deleting `[marketplaces.wakatime]` from `config.toml` leaves
`~/.codex/.tmp/marketplaces/wakatime/.codex-marketplace-install.json` behind. The
marketplace then does not appear in `codex plugin marketplace list`, but
`marketplace add` still fails with "already added from a different source".
Recovery is `codex plugin marketplace remove wakatime` followed by a normal
install.

## Marketplace source form (verified 2026-09-18)

- `claude plugin marketplace add wakatime/claude-code-wakatime` prints
  "SSH not configured, cloning via HTTPS" — the GitHub shorthand attempts SSH
  first, so on a machine with GitHub SSH keys the installer's clone would depend
  on those credentials. Passing the HTTPS clone URL skips that attempt.
- Both CLIs accept the full clone URL and record the same source afterwards, so
  the URL form is used for adding. Codex records `source` either way; Claude Code
  records `{"source":"github","repo":...}` for the shorthand and
  `{"source":"git","url":...}` for the URL, so state checks accept both.
