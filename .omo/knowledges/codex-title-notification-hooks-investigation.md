# Codex title generation and Gotify notification investigation

## Scope

Investigated on 2026-08-30 with `codex-cli 0.151.0` (`rust-v0.151.0`, commit
`78c290807ce710180111df227df3b7a4fe845452`). No notification configuration or
runtime behavior was changed during this investigation.

## Symptom and confirmed cause

The first prompt in a new interactive TUI thread starts a second, hidden thread
that generates a concise thread title. The hidden turn uses a prompt beginning
with `Generate a concise, single-line task title` and ending with `Do not answer
the request.`

The hidden title thread emits the legacy `agent-turn-complete` notification. A
configured top-level `notify = [...]` command therefore cannot distinguish it
from a normal completed turn and sends an unwanted Gotify message.

Local evidence showed consecutive visible and hidden thread IDs. The hidden ID
appeared in `~/.codex/log/gotify-notify.log` as
`payload_loaded event=agent-turn-complete`, but it had no rollout file under
`~/.codex/sessions` and no row in `state_5.sqlite.threads` because the title
thread is ephemeral.

## Relevant upstream behavior

The TUI implementation introduced by merged PR
<https://github.com/openai/codex/pull/40492>:

- starts title generation after the first user-message item when the thread has
  no explicit name;
- creates a bounded hidden temporary thread;
- sets `ephemeral = true` and `thread_source = Feature("system")`;
- explicitly overrides `features.hooks = false` for that temporary thread;
- does not clear the inherited top-level `notify` command.

The legacy notification and the lifecycle hook engine are configured
independently. `legacy_notify_argv` is converted into an `AfterAgent` hook even
when the lifecycle hook feature is disabled, while `feature_enabled` only gates
the lifecycle hook engine. This explains why the title thread skips configured
`Stop` hooks but still invokes top-level `notify`.

As of the investigation date, the same temporary-thread configuration remains
on upstream `main`. No matching upstream issue or fix was found, and there is
no documented configuration switch for automatic TUI title generation.

## Migration assessment

A root `Stop` lifecycle hook is a good replacement trigger for ordinary
completion notifications in the current configuration:

- the title thread explicitly disables lifecycle hooks, so it cannot invoke the
  Gotify `Stop` handler;
- thread-spawned agents route to `SubagentStop`, not root `Stop`;
- `Stop` receives JSON on stdin with `session_id`, `turn_id`, `cwd`, `model`,
  `permission_mode`, `stop_hook_active`, and `last_assistant_message`;
- `Stop` does not support a matcher, so filtering must remain in the handler if
  any is needed.

Hooks replace the Codex trigger mechanism, not the Gotify delivery mechanism.
Gotify still needs either a command handler, an MCP server/tool, or an inline
shell pipeline. Reusing a small Python handler is safer than embedding JSON
parsing, HTTP requests, and credential handling in TOML.

The existing `codex-gotify-notify.py` already accepts JSON from stdin and can
extract `last_assistant_message`, but it currently treats only
`agent-turn-complete` as a normal completion. It would need an explicit root
`Stop` branch before it could be registered as a completion hook.

Important migration caveats:

- the existing handler may spend up to 120 seconds summarizing and another 10
  seconds on Gotify HTTP, so a `Stop` command should normally be asynchronous
  or reduced to a fast enqueue operation;
- Codex aborts outstanding asynchronous hook tasks when the session shuts down,
  so an immediate exit can lose an in-process background notification;
- all matching `Stop` handlers start concurrently. If another `Stop` handler
  requests continuation, a notification handler can run on the initial stop
  attempt before the turn truly finishes;
- hook definitions require trust review after they change;
- the current installer owns the top-level `notify` key:
  `pull.py::ensure_codex_notify_config_lines()` restores it on every install.
  A real migration must update the installer and README as well as user config,
  otherwise normal turns would produce duplicate notifications.

## Alternative minimal workaround

Keeping legacy `notify` and filtering the fixed title-generation prompt inside
`codex-gotify-notify.py` is the smallest local change. It preserves the current
detached-process behavior but relies on a prompt signature that upstream may
change. Filtering every thread without a rollout file would be too broad because
other legitimate ephemeral or app-server threads may also be unpersisted.

## Applied minimal workaround

On 2026-08-30, the repository copy and the active
`~/.codex/codex-gotify-notify.py` copy were updated together. The handler now
skips only an `agent-turn-complete` event whose normalized input message:

- starts with `Generate a concise, single-line task title`;
- contains `User prompt:`; and
- contains `Do not answer the request.`

The check runs immediately after payload parsing and logging, before thread
source scans, summarization, deduplication, or the Gotify request. The skip is
recorded as `run_skip reason=thread_title_generation`.

A synthetic regression test first reproduced the old behavior with one
summarizer call and one fake push. After the patch, the title event made zero
summarizer and push calls, while a normal completion still made one of each.
Both script copies passed `py_compile`, had identical SHA-256 hashes, and
`git diff --check` passed. No real Gotify request was sent during testing.

The cleaner upstream fix would be to clear `notify` in the isolated title-thread
configuration, or to prevent legacy `AfterAgent` notifications for ephemeral
system-feature threads.

## Sources

- Hooks documentation: <https://learn.chatgpt.com/docs/hooks>
- Legacy notify documentation:
  <https://developers.openai.com/codex/config-advanced#notifications>
- Title implementation:
  <https://github.com/openai/codex/blob/78c290807ce710180111df227df3b7a4fe845452/codex-rs/tui/src/app/thread_title.rs>
- Temporary thread isolation:
  <https://github.com/openai/codex/blob/78c290807ce710180111df227df3b7a4fe845452/codex-rs/tui/src/temporary_structured_request.rs>
- Hook registry separation:
  <https://github.com/openai/codex/blob/78c290807ce710180111df227df3b7a4fe845452/codex-rs/hooks/src/registry.rs>
- Stop input implementation:
  <https://github.com/openai/codex/blob/78c290807ce710180111df227df3b7a4fe845452/codex-rs/hooks/src/events/stop.rs>
