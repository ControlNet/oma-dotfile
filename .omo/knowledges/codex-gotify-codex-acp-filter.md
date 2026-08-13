# Codex Gotify: filtering `codex-acp`

## Symptom and evidence

On 2026-08-13, Gotify delivered this notification from the Codex notify hook:

```text
Codex :: _default@neuro-core
✅ VLA-1 is blocked: OpenAI API credentials must be configured to proceed.
```

`~/.codex/log/gotify-notify.log` linked it to thread
`019ffb94-f0b2-7221-9c7d-7c06da2683f9` at `14:49:02Z`. The matching
Paperclip ACP session record identified the launcher as:

```text
.../node_modules/.bin/codex-acp
```

The live process shape was `codex-acp -> codex app-server`. The adapter inherits
Codex configuration, so App Server invoked the normal `notify` hook after the
turn completed.

## Original input

The ACP input was a Paperclip `issue_recovery_action_restored` wake for VLA-1,
not a short interactive prompt. It told Head of Autonomous to recover the task
after a `configuration_incomplete` failure in the managed Codex home. The
underlying issue asked it to hire a founding engineer, write a hiring plan, and
delegate roadmap work. The recovery instruction said to repair/bind the missing
credentials and return the issue for retry instead of writing the deliverable.

Do not copy environment values or API credentials from ACP session records into
logs or documentation.

## Root cause and fix

Codex completion payloads produced through App Server do not expose a reliable
ACP-specific source field. Filtering every App Server turn would also suppress
non-ACP clients. `codex-gotify-notify.py` therefore inspects its ancestor
process argv and skips only when it finds an actual `codex-acp` executable or a
Node/Bun script under `@agentclientprotocol/codex-acp`.

The filter runs before Gotify configuration and summarization. A skip is visible
as:

```text
run_skip reason=codex_acp event=agent-turn-complete thread_id=<thread-id>
```

The installer copies the repository hook to `~/.codex/codex-gotify-notify.py`.
Run `python3 pull.py` after pulling this change on another machine.

## Verification

```bash
/home/ubuntu/miniconda3/bin/python3 -m py_compile codex-gotify-notify.py
git diff --check
```

Manual A/B QA used the same completion payload twice: through a temporary Node
launcher named `codex-acp`, it logged `run_skip reason=codex_acp`; directly, it
continued to the ordinary `missing_gotify_config` branch. The installed hook was
then tested through the ACP-shaped ancestor and produced the same skip with exit
code 0. Environment variables for Gotify were explicitly unset during QA, so no
real notification was sent.
