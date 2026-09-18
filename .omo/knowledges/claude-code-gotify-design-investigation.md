# Claude Code Gotify integration

Investigated and implemented on 2026-09-06. The local `claude --version`
reports `2.1.263 (Claude Code)`. The notifier is installed as a personal
skills-directory plugin. No real Gotify notification was sent during
verification.

## Implemented layout and installation

- Repository source: `claude-plugins/gotify-notify/`.
- Personal install target: `~/.claude/skills/gotify-notify/`, or
  `$CLAUDE_CONFIG_DIR/skills/gotify-notify/` when overridden.
- `pull.py` replaces only this managed directory. It preserves Claude
  `settings.json`, unrelated skills, and other plugins.
- Installation rewrites each command hook's interpreter to `sys.executable`,
  while the script path remains relative to `${CLAUDE_PLUGIN_ROOT}`.
- The plugin manifest, event hooks, and Python standard-library handler live in
  `.claude-plugin/plugin.json`, `hooks/hooks.json`, and `scripts/notify.py`.
- Claude CLI validation passed, and `claude plugin list` reported
  `gotify-notify@skills-dir` at user scope with status `loaded`.

The handler supports Stop, StopFailure, selected Notification events,
AskUserQuestion PreToolUse, and opt-in SubagentStop. It uses bounded HTTP
timeouts, preview fallback, optional OpenAI-compatible summarization, redacted
logs, and SQLite-backed cross-process deduplication. Gotify and summarizer
credentials are read only from environment variables.

Verification commands completed successfully:

```bash
python3 -m unittest -v tests.test_claude_gotify_notify
python3 -m unittest -v tests.test_codex_gotify_notify
node --test tests/omp-gotify-notify.test.mjs
python3 -m py_compile pull.py claude-plugins/gotify-notify/scripts/notify.py
claude plugin validate claude-plugins/gotify-notify
```

An installed-handler `--dry-run` produced the expected title and completion
message without using the network or creating deduplication state.

## Existing repository

- `plugins/gotify-notify.js` is an OpenCode event plugin.
- `omp-gotify-notify.js` is an OMP extension with bounded network requests,
  summarization, preview fallback, deduplication, and redacted diagnostics.
- `codex-gotify-notify.py` is a standalone Python standard-library handler.
  Its title/recap/source/ACP filters and payload interpretation are Codex-specific.
- `pull.py` currently installs OpenCode, OMO, OMP, and Codex assets; it has no
  Claude Code installation step.

## Recommended implementation direction

Prefer a personal skills-directory plugin at `~/.claude/skills/gotify-notify/`.
Follow-up investigation found official support for automatic plugin discovery
there, superseding the initial recommendation to merge user-level hooks into
settings.json. The local `claude plugin init --help` explicitly confirms this
auto-load behavior. No marketplace or install command is required.

The directory must contain `.claude-plugin/plugin.json`; bundle notification
events in `hooks/hooks.json` and the handler under `scripts/`, referencing it
through `${CLAUDE_PLUGIN_ROOT}`. Claude loads it in place as
`gotify-notify@skills-dir` on the next session, without a cached copy. A plain
SKILL.md without the manifest is a skill, not an automatically active hook plugin.

Reuse existing delivery and summarization patterns, but implement Claude-specific
input adaptation and event filtering. Python's standard library would avoid
adding a runtime package dependency. The installer can copy only the managed
plugin directory, preserving unrelated plugins and skills.

Hook and other component changes require `/reload-plugins` or a session restart.
Disable with `claude plugin disable gotify-notify@skills-dir`. A project plugin
can live under the primary working directory's `.claude/skills/`, but requires
explicit trust for that folder and is not discovered by walking up from a nested
working directory. Personal scope is the appropriate fit for this notifier.

Alternative loading mechanisms are `claude --plugin-dir` for a session-local
plugin and marketplace add/install for distribution. Marketplace installs
normally copy a version into `~/.claude/plugins/cache`; they are unnecessary
for the user's preferred folder-based workflow.

## Event mapping and limitations

- `Stop`: main-agent response ended, not proof of successful task completion.
  Use `last_assistant_message` for summaries. Transcripts are asynchronous and
  may not contain the final message yet. User interrupts do not fire Stop.
- `StopFailure`: API failure ending a turn, instead of Stop. This is not a
  catch-all process crash or ordinary tool failure event.
- `Notification` / `permission_prompt`: delayed attention signal, about six
  seconds; terminal typing defers it. Also covers sandbox network prompts in
  current versions.
- `PermissionRequest`: immediate tool permission signal, also possible for
  noninteractive subagents that cannot display a prompt. It does not cover
  sandbox network prompts. Choose deliberately between this and delayed
  notifications, or coordinate deduplication when combining them.
- `PreToolUse` / `AskUserQuestion`: proposed immediate question notification
  with access to tool input. This signals an attempted question call; another
  hook may still block it. Validate actual question UX during implementation.
- `Notification` / `elicitation_dialog` and `elicitation_url_dialog`: MCP user
  input requests, not generic AskUserQuestion events.
- `Notification` / `idle_prompt`: about 60 seconds after response completion,
  only without further typing. Disable by default if Stop already notifies.
- `SubagentStop`: separate optional signal; default off to reduce noise.
  Tool hooks also run inside subagents; filter `agent_id` if appropriate.

`stop_hook_active` indicates continuation caused by a previous Stop hook. It
does not prove the current Stop will be accepted. Other Stop hooks may request
more work. Current Stop payloads also expose background tasks and scheduled
wakeups, which can help distinguish a completed response from pending work.

Command hooks support `async: true`; implement network deadlines inside the
script because background async hooks do not enforce the hook timeout. Plain
`claude -p` teardown kills remaining async hooks, so headless support needs an
explicit delivery strategy. Notification handlers should emit no control output
and should not block the agent on delivery failure.

HTTP hooks POST the original event JSON without a configurable body template.
They suit a forwarding service that translates events to Gotify messages.
Direct raw forwarding is insufficient for Stop summaries, consistent titles,
deduplication, and event formatting. Current hooks also support `mcp_tool`,
which invokes a connected MCP server deterministically; building such a server
solely for this notifier adds unnecessary infrastructure.

Use inherited environment configuration for Gotify credentials and the existing
summarizer configuration. Never place credential values in settings, source,
or diagnostics. Local user hooks do not automatically carry into cloud sessions.

## Official references

- https://code.claude.com/docs/en/hooks
- https://code.claude.com/docs/en/hooks-guide
- https://code.claude.com/docs/en/plugins
- https://code.claude.com/docs/en/plugins-reference
- https://code.claude.com/docs/en/tools-reference#askuserquestion-tool-behavior

These describe current documented behavior, not end-to-end validation of a
Gotify integration on the local installation.
