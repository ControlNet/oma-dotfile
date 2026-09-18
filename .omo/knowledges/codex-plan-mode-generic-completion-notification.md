# Codex Plan mode can produce a generic completion notification

Investigated on 2026-09-16 with `codex-cli 0.154.0` after Gotify delivered:

```text
Codex :: minecraft-matrix-bridge@ansr-nectar-4
✅ Agent turn completed
```

## Confirmed event

`~/.codex/log/gotify-notify.log` records the matching successful delivery at
2026-09-16 00:14:03 +1000:

```text
payload_loaded event=agent-turn-complete thread_id=01a0a55a-f10a-7f10-ae27-6e199db82a7d
summarizer_skip reason=empty_source
run_success event=agent-turn-complete message_chars=22
```

The persisted rollout for that thread is:

```text
~/.codex/sessions/2026/09/15/rollout-2026-09-15T23-56-35-01a0a55a-f10a-7f10-ae27-6e199db82a7d.jsonl
```

At 2026-09-15T14:14:01Z, the turn emitted a `Plan` item and a
`response_item` containing the full `<proposed_plan>` as an assistant
`final_answer`. At 14:14:02Z, its `task_complete` event had
`last_agent_message: null`.

The top-level Codex `notify` command receives an `agent-turn-complete` payload.
For this Plan mode turn, that payload had no usable `last-assistant-message`.
`codex-gotify-notify.py::_extract_message()` therefore could not summarize the
plan and selected its completion fallback, exactly `✅ Agent turn completed`.

The title is independently built by `_build_notify_title()` as:

```text
Codex :: <basename(payload cwd)>@<socket hostname>
```

The event cwd was `/home/zhixi/GitRepos/minecraft-matrix-bridge`, and the host
name was `ansr-nectar-4`, which reproduces the observed title exactly.

## Scope

This event was a visible Plan mode completion. It was not an ephemeral title
generation or conversation recap turn; the installed notifier already filters
both prompt signatures before delivery. The repository and installed notifier
copies had the same SHA-256 hash during the investigation.

Official Codex configuration documentation defines top-level `notify` as an
argv command that receives a JSON notification payload:

- https://learn.chatgpt.com/docs/config-file/config-reference

## Diagnostic commands

```bash
rg -n -B5 -A1 \
  'run_success event=agent-turn-complete message_chars=22$' \
  "$HOME/.codex/log/gotify-notify.log"

jq -rc \
  'select(.ordinal == 411 or .ordinal == 412 or .ordinal == 415) |
   {ordinal, timestamp, record: .type, payload: .payload}' \
  "$HOME/.codex/sessions/2026/09/15/rollout-2026-09-15T23-56-35-01a0a55a-f10a-7f10-ae27-6e199db82a7d.jsonl"
```

Expected signals: the notification log reports `empty_source` followed by a
22-character successful completion message, while the rollout contains the
plan response followed by `task_complete.last_agent_message = null`.
