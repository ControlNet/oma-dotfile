# Codex Gotify Auto Approval Filter

Codex auto approval reviewer turns can trigger the same `notify` hook as normal
agent turns. In observed runs, those reviewer turns did not always produce a
`~/.codex/sessions/**/rollout-*-<thread_id>.jsonl` file, so filtering only via
session metadata can miss them.

The reliable local signal was in `~/.codex/log/codex-tui.log`: the reviewer
thread appears with `model=codex-auto-review` for the same `thread_id` that the
notify payload reports. `codex-gotify-notify.py` now falls back to scanning the
recent TUI log for that marker and skips Gotify messages for those turns.

Verification commands:

```bash
python3 -m py_compile codex-gotify-notify.py
python3 - <<'PY'
import importlib.util
import os
import tempfile
from pathlib import Path

with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    log_path = tmp_path / "codex-tui.log"
    thread_id = "019e5d81-8ff5-7f10-95fc-ed3121f1c642"
    log_path.write_text(
        f"INFO session_loop{{thread_id={thread_id}}}:turn{{model=codex-auto-review}} close\n",
        encoding="utf-8",
    )
    os.environ["HOME"] = tmp
    os.environ["CODEX_NOTIFY_TUI_LOG_FILE"] = str(log_path)
    os.environ["CODEX_NOTIFY_SESSIONS_DIR"] = str(tmp_path / "missing-sessions")

    spec = importlib.util.spec_from_file_location("codex_notify", "codex-gotify-notify.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    payload = {"type": "agent-turn-complete", "thread_id": thread_id}
    assert module._is_auto_approval_event(payload) is True
    assert module._extract_message(payload, include_prompt=False) == ("", "")
print("auto approval tui-log fallback: ok")
PY
```
