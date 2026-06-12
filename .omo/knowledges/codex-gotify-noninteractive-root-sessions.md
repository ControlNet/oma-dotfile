# Codex Gotify notifications skipped by over-broad noninteractive detection

## Symptom

Codex Gotify notifications can work in Codex Desktop or VS Code-backed sessions while apparently identical settings on a remote host produce no notification for a normal-looking interactive `codex` TUI session.

## Root Cause

`~/.codex/codex-gotify-notify.py` used an over-broad noninteractive heuristic. It treated any root session with `source == "cli"` or `source == "exec"` plus `approval_policy == "never"` as noninteractive unless `CODEX_NOTIFY_NONINTERACTIVE=1` or `OPENCODE_NOTIFY_NONINTERACTIVE=1` was set.

That is wrong because ordinary interactive `codex` TUI sessions are recorded as:

```text
originator = "codex-tui"
source = "cli"
```

They can also legitimately use:

```text
approval_policy = "never"
```

`approval_policy = "never"` means "do not ask for tool approval"; it does not mean "noninteractive." The actual noninteractive source should be `source == "exec"` for `codex exec`.

The corrected skip rule is:

- session source is `source == "exec"`
- the session payload contains `approval_policy == "never"`
- the session is not a subagent
- `CODEX_NOTIFY_NONINTERACTIVE` / `OPENCODE_NOTIFY_NONINTERACTIVE` is unset or false

When this happens, `~/.codex/log/gotify-notify.log` contains:

```text
noninteractive_root_detected source=sessions thread_id=<session-id>
run_skip reason=noninteractive_root_session event=agent-turn-complete thread_id=<session-id>
```

The decision is cached in:

```text
~/.codex/.gotify-notify-thread-source-cache.json
```

## Diagnostic Commands

Check the session source:

```bash
python3 - <<'PY'
import json
from pathlib import Path

sid = "<session-id>"
paths = list((Path.home() / ".codex/sessions").glob(f"**/rollout-*-{sid}.jsonl"))
for path in paths:
    first = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    payload = first["payload"]
    print({
        "id": payload.get("id"),
        "originator": payload.get("originator"),
        "source": payload.get("source"),
        "cli_version": payload.get("cli_version"),
        "cwd": payload.get("cwd"),
    })
PY
```

Check the notification log:

```bash
rg -n '<session-id>|noninteractive_root|run_skip' ~/.codex/log/gotify-notify.log
```

Check the cached classification:

```bash
python3 - <<'PY'
import json
from pathlib import Path

sid = "<session-id>"
path = Path.home() / ".codex/.gotify-notify-thread-source-cache.json"
data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
print(data.get(sid))
PY
```

## Fix Options

For a one-off noninteractive `codex exec` run that should still notify:

```bash
CODEX_NOTIFY_NONINTERACTIVE=1 codex exec "your prompt"
```

For persistent behavior, export it in the shell startup file used to launch Codex:

```bash
export CODEX_NOTIFY_NONINTERACTIVE=1
```

Interactive `codex` TUI sessions should not need this override, even when `approval_policy = "never"`.
