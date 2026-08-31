# OMP Gotify notifier audit

Audited against `omp/18.0.11`, which was also the latest upstream release on
2026-08-31.

## Current trigger flow

- `agent_end` sends completion or error notifications using the last assistant
  message.
- `tool_call` detects the `ask` tool and sends a waiting-for-input notification.
- `auto_retry_end` sends another error notification when a retry saga fails.
- Completion text can be summarized through OpenAI-compatible
  `/chat/completions`, then `/responses`, before Gotify delivery.

## OMP 18 event semantics

- `agent_end` remains the correct public terminal hook. `turn_end` fires for
  every model turn, and `session_shutdown` only fires when OMP exits.
- `AgentEndEvent.willContinue` is true when OMP has already scheduled an
  automatic continuation. Extensions must skip user-visible completion/error
  handling in that case. OMP's own Warp bridge uses this exact guard.
- OMP's native completion/error notifications also classify `aborted` turns as
  neither completion nor error.
- For ask attention, OMP's Warp bridge listens to `tool_execution_start`, which
  is more precise than the pre-execution `tool_call` hook.

## Implemented changes

1. `agent_end` returns immediately for `event.willContinue` and aborted turns.
2. Terminal `agent_end` is the only completion/error notification source, so a
   failed retry saga cannot also notify through `auto_retry_end`.
3. Ask notifications use `tool_execution_start` and deduplicate by `toolCallId`.
4. Summarizer requests are capped at 8 seconds per route and Gotify delivery
   is capped at 5 seconds, keeping worst-case network waiting near 21 seconds.
5. Gotify and summarizer HTTP failures write bounded, redacted diagnostics to
   `~/.omp/logs/gotify-notify.log`, with one rotated `.1` file.
6. Notification messages are plain text and no longer escape Markdown syntax.
7. Native OMP completion, error, and ask notifications are disabled so Gotify
   remains the sole configured channel.
8. Node's built-in test runner covers terminal classification, retry behavior,
   ask timing and deduplication, missing configuration, and HTTP failure logging.

There is no newer Gotify-specific OMP API in 18.0.11. The best implementation
is still an extension, aligned with OMP's own terminal-event classification.
