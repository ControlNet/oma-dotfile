# Codex conversation recap triggers legacy notifications

Investigated on 2026-09-05 against installed `codex-cli 0.153.4` and upstream
tag `rust-v0.153.4`. The initial investigation did not change notification
behavior or user configuration. The subsequently authorized workaround is
documented below. No real test notifications were sent.

## Active implementation

- User-level `~/.codex/config.toml` registers the installed
  `~/.codex/codex-gotify-notify.py` through top-level `notify`.
- The installed script is byte-for-byte identical to the repository script.
- No command in the active `~/.codex/hooks.json` references Gotify.
- The script parses the completion JSON, filters title generation, ACP,
  noninteractive sessions, approval reviewers, and subagents, then optionally
  summarizes the assistant response, deduplicates, and sends it to Gotify.
- At investigation time, `_is_thread_title_generation_event()` recognized the
  fixed title prompt, but there was no equivalent recap filter.

## Confirmed source-level cause

`codex-rs/tui/src/app/recap.rs` starts a hidden thread with
`start_temporary_thread()` and submits `run_temporary_structured_turn()`.
Both automatic and manual recaps use this path. The fixed input starts with:

> Write a brief catch-up for a user returning to this Codex task.

The prompt also includes `In at most 40 words and one or two plain-text
sentences` and the delimiter `Recent conversation:`. The response schema is
an object with one required string property named `recap`.

`codex-rs/tui/src/temporary_structured_request.rs` sets `ephemeral = true`,
`thread_source = Feature("system")`, and `features.hooks = false`, but does
not clear inherited `notify` configuration.

`codex-rs/hooks/src/registry.rs` independently converts `legacy_notify_argv`
into an `AfterAgent` handler. The lifecycle engine's `feature_enabled` flag
does not gate this handler. `legacy_notify.rs` serializes that event as
`agent-turn-complete` and starts the configured command.

The legacy payload includes thread/turn IDs, cwd, optional client, input
messages, and the last assistant message. It has no dedicated recap event
type or ephemeral/system-thread classification. The recap therefore reaches
the ordinary completion branch in `_extract_message()`. Session-based
filters cannot reliably classify an ephemeral thread without a rollout.

## Local evidence and limits

The notification log contains 18 successful runs whose thread IDs have no
matching rollout in the current sessions directory. For example, on
2026-09-05 at 17:30:21 +1000, an unpersisted thread reached
`payload_loaded event=agent-turn-complete` and `summarizer_attempt
input_chars=96`, then `run_success` at 17:30:36.

These records are consistent with hidden recap threads, but the log does not
retain original input/output payloads, so they do not individually prove that
each unpersisted thread was a recap. Source inspection establishes the
notification path; no live recap was triggered during this investigation.

## Options

1. Minimal local workaround: filter the fixed recap input prompt immediately
   after parsing, alongside the title-generation filter. Match multiple
   signature parts; do not filter any response mentioning recap or any thread
   missing a rollout. This preserves both the recap UI and normal Gotify
   notifications but depends on upstream prompt wording.
2. Disable automatic recap with `tui.auto_recap = false`. The official
   changelog documents this option, and the installed version's source
   supports it. Manual `/recap` remains available and still uses the same
   legacy notification path.
3. Migrate completion notifications to lifecycle `Stop`; account for the
   installer, handler event parsing, and delivery lifecycle as described in
   `codex-title-notification-hooks-investigation.md`.

Automatic recap scheduling in this version requires at least three completed
turns, at least two additional completed turns after a previous recap, and
three minutes since the later of focus loss and the last completed turn.
The request is also checked for freshness and a pending/running user turn.

## Sources

- https://developers.openai.com/codex/config-advanced/#notifications
- https://developers.openai.com/codex/changelog/
- https://github.com/openai/codex/blob/rust-v0.153.4/codex-rs/tui/src/app/recap.rs
- https://github.com/openai/codex/blob/rust-v0.153.4/codex-rs/tui/src/temporary_structured_request.rs
- https://github.com/openai/codex/blob/rust-v0.153.4/codex-rs/hooks/src/registry.rs
- https://github.com/openai/codex/blob/rust-v0.153.4/codex-rs/hooks/src/legacy_notify.rs

## Applied workaround and verification

On 2026-09-05, added `_is_conversation_recap_event()` next to the existing
title filter and synchronized the repository script to the installed hook.
The previous installed script was backed up to a temporary directory before
atomic replacement. No Codex configuration changes are required.

Only completion events whose normalized input starts with the fixed recap
prefix and includes both the 40-word instruction and `Recent conversation:`
are skipped. The filter supports the existing top-level/nested payload
formats and records `run_skip reason=conversation_recap` before process or
session scans, summarization, deduplication, and delivery. Both automatic
recap and manual `/recap` use this prompt; the recap UI remains enabled.

`tests/test_codex_gotify_notify.py` contains explicitly synthetic events and
mocked summarization/delivery. Network access is blocked during tests. The
regression suite reproduced the missing filter before implementation and
all eight tests passed afterward, including ordinary completions with recap
output, quoted prompts, incomplete signatures, stdin/nested payloads,
case/whitespace normalization, and the existing title filter.

Run from the repository root:

```bash
python3 -m unittest discover -s tests -p 'test_codex_gotify_notify.py' -v
python3 -m py_compile codex-gotify-notify.py "$HOME/.codex/codex-gotify-notify.py"
cmp codex-gotify-notify.py "$HOME/.codex/codex-gotify-notify.py"
git diff --check
```

Expected: eight tests pass; compilation, comparison, and whitespace checks
exit successfully. After an actual recap, check the skip marker with:

```bash
rg 'run_skip reason=conversation_recap' "$HOME/.codex/log/gotify-notify.log"
```

This is a prompt-signature workaround and may need adjustment after an
upstream prompt change. No real recap was triggered during verification.
