#!/usr/bin/env python3
"""Forward the Antigravity CLI's (agy) Stop hook to Gotify.

agy runs a hook synchronously, blocking its agent loop, and reads the hook's stdout as JSON.
So the hook prints `{}` at once and hands delivery, which may wait on a summarizer, to a
detached copy of itself (`--worker`). agy's payload has no response text; it comes from the
conversation's transcript.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

DEFAULT_MAX_CHARS = 280
DEFAULT_HEAD = 80
DEFAULT_TAIL = 80
DEFAULT_SUMMARIZER_TIMEOUT_SEC = 120
MAX_LOG_BYTES = 256 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_TRANSCRIPT_BYTES = 1024 * 1024  # read from the end; the last turn is all that is needed
# Termination reasons worth a message besides a finished turn (ERROR has its own text).
EARLY_STOPS = {"MAX_INVOCATIONS", "MAX_FORCED_INVOCATIONS", "MAX_TOKEN_BUDGET_EXCEEDED"}
USER_AGENT = "AntigravityGotifyNotify/1.0"


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def env_first(*names: str, default: str = "") -> str:
    for name in names:
        value = env(name)
        if value:
            return value
    return default


def env_bool(name: str, default: bool) -> bool:
    value = env(name).lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def env_int(name: str, default: int, minimum: int = 0, maximum: int | None = None) -> int:
    try:
        value = int(env(name, str(default)))
    except ValueError:
        value = default
    value = max(minimum, value)
    return min(value, maximum) if maximum is not None else value


def normalize_text(value: object) -> str:
    return " ".join(str(value or "").split())


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3] + "..."


def preview(text: str) -> str:
    text = normalize_text(text)
    head = env_int("AGY_NOTIFY_HEAD", DEFAULT_HEAD)
    tail = env_int("AGY_NOTIFY_TAIL", DEFAULT_TAIL)
    if len(text) <= head + tail + 3:
        return text
    if not tail:
        return text[:head]
    if not head:
        return text[-tail:]
    return text[:head] + "..." + text[-tail:]


def data_dir() -> Path:
    """agy gives a plugin's hooks PLUGIN_DATA; the plugin dir itself is replaced on reinstall."""
    custom = env("PLUGIN_DATA")
    if custom:
        return Path(custom)
    return Path.home() / ".gemini" / "antigravity-cli" / "plugin_data" / "oma-dotfile"


def log_path() -> Path:
    custom = env("AGY_NOTIFY_LOG_FILE")
    return Path(custom).expanduser() if custom else data_dir() / "gotify-notify.log"


def log(stage: str, detail: str = "") -> None:
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size >= MAX_LOG_BYTES:
            path.replace(path.with_name(path.name + ".1"))
        suffix = f" {truncate(normalize_text(detail), 160)}" if detail else ""
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {stage}{suffix}\n")
    except OSError:
        pass


def transcript_rows(path: Path) -> dict[int, dict[str, object]]:
    """The transcript's steps by step_index, from at most its last MAX_TRANSCRIPT_BYTES."""
    try:
        with path.open("rb") as handle:
            size = handle.seek(0, os.SEEK_END)
            handle.seek(max(0, size - MAX_TRANSCRIPT_BYTES))
            raw = handle.read()
    except OSError:
        return {}
    lines = raw.decode("utf-8", errors="replace").splitlines()
    if size > MAX_TRANSCRIPT_BYTES:
        lines = lines[1:]  # the first line was cut by the seek
    rows: dict[int, dict[str, object]] = {}
    for line in lines:
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and isinstance(parsed.get("step_index"), int):
            rows[parsed["step_index"]] = parsed
    return rows


def last_response(transcript: object) -> str:
    """The model's final text in the last turn; '' when it has none.

    transcript.jsonl cuts long contents (`truncated_fields`); transcript_full.jsonl beside it
    keeps them, so its steps win.
    """
    if not isinstance(transcript, str) or not transcript:
        return ""
    path = Path(transcript)
    rows = transcript_rows(path)
    rows.update(transcript_rows(path.with_name("transcript_full.jsonl")))
    steps = [rows[index] for index in sorted(rows)]
    turn_start = max((i for i, step in enumerate(steps) if step.get("type") == "USER_INPUT"), default=-1)
    for step in reversed(steps[turn_start + 1:]):
        content = step.get("content")
        if step.get("source") == "MODEL" and step.get("type") == "PLANNER_RESPONSE" \
                and isinstance(content, str) and content.strip():
            return content
    return ""


def event_message(payload: dict[str, object]) -> tuple[str, str] | None:
    """(message, text to summarize) for a Stop worth a message, else None."""
    if payload.get("hookEventName") != "Stop":
        return None
    reason = payload.get("terminationReason")
    if reason == "NO_TOOL_CALL":
        # fullyIdle is false while background tasks still run; their end is the real finish.
        if not env_bool("AGY_NOTIFY_COMPLETE", True) or payload.get("fullyIdle") is False:
            return None
        response = last_response(payload.get("transcriptPath"))
        return ("Response finished: " + preview(response), response) if response else None
    if reason == "ERROR" and env_bool("AGY_NOTIFY_ERROR", True):
        return "Error: " + (normalize_text(payload.get("error")) or "unknown"), ""
    if reason in EARLY_STOPS and env_bool("AGY_NOTIFY_ERROR", True):
        return f"Stopped: {reason}", ""
    return None


def project(payload: dict[str, object]) -> str:
    """Where the agent works: agy runs hooks in the plugin dir, so not os.getcwd()."""
    workspaces = payload.get("workspacePaths")
    first = workspaces[0] if isinstance(workspaces, list) and workspaces else ""
    path = normalize_text(payload.get("cwd")) or normalize_text(first)
    return Path(path).name if path else "unknown-project"


def title(payload: dict[str, object]) -> str:
    custom = env("AGY_NOTIFY_TITLE")
    if custom:
        return custom
    return f"Antigravity CLI :: {project(payload)}@{socket.gethostname() or 'unknown-host'}"


def gotify_config() -> tuple[str, str] | None:
    base = env("GOTIFY_URL").rstrip("/")
    token = env_first("GOTIFY_TOKEN_FOR_AGY", "GOTIFY_TOKEN_FOR_OPENCODE")
    return (base, token) if base and token else None


def endpoint(base: str, suffix: str) -> str:
    return base if base.endswith(suffix) else base + suffix


def post_json(url: str, body: dict[str, object], headers: dict[str, str], timeout: int,
              stage: str) -> dict[str, object] | None:
    request = urllib.request.Request(
        url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers}, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            log(stage, "response_too_large")
            return None
        if not raw:
            return {}
        parsed = json.loads(raw.decode("utf-8"))
        return parsed if isinstance(parsed, dict) else {}
    except urllib.error.HTTPError as error:
        log(stage, f"HTTP_{error.code}")
    except (urllib.error.URLError, TimeoutError, OSError, UnicodeError, json.JSONDecodeError) as error:
        log(stage, type(error).__name__)
    return None


def extract_model_text(payload: dict[str, object]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and normalize_text(output_text):
        return normalize_text(output_text)
    output = payload.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict) or not isinstance(item.get("content"), list):
                continue
            for part in item["content"]:
                if isinstance(part, dict) and isinstance(part.get("text"), str) and normalize_text(part["text"]):
                    return normalize_text(part["text"])
    choices = payload.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
                continue
            content = choice["message"].get("content")
            if isinstance(content, str) and normalize_text(content):
                return normalize_text(content)
    return ""


def summarize(text: str) -> str:
    """One short sentence from an OpenAI-compatible API, as the other agents' notifiers do."""
    model = env("GOTIFY_NOTIFY_SUMMARIZER_MODEL")
    base = env("GOTIFY_NOTIFY_SUMMARIZER_ENDPOINT").rstrip("/")
    api_key = env("GOTIFY_NOTIFY_SUMMARIZER_API_KEY")
    clipped = truncate(normalize_text(text), env_int("AGY_NOTIFY_SUMMARIZER_MAX_INPUT_CHARS", 5000, minimum=1))
    if not model or not base or not api_key or not clipped:
        return ""
    prompt = (
        "Output plain text only. Use the same language as the input. "
        "Summarize the completed response in one short sentence of at most 80 characters.\n\n"
        + clipped
    )
    headers = {"Authorization": f"Bearer {api_key}", "api-key": api_key, "User-Agent": USER_AGENT}
    timeout = env_int("AGY_NOTIFY_SUMMARIZER_TIMEOUT_SEC", DEFAULT_SUMMARIZER_TIMEOUT_SEC, minimum=1)
    chat = post_json(
        endpoint(base, "/chat/completions"),
        {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 80},
        headers, timeout, "summarizer_chat",
    )
    if chat is not None and (result := extract_model_text(chat)):
        return truncate(result, 200)
    responses = post_json(
        endpoint(base, "/responses"),
        {"model": model, "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
         "reasoning": {"effort": "low"}, "max_output_tokens": 80},
        headers, timeout, "summarizer_responses",
    )
    return truncate(extract_model_text(responses or {}), 200)


def deliver(payload: dict[str, object]) -> None:
    result = event_message(payload)
    config = gotify_config()
    if result is None or config is None:
        log("skip", "nothing_to_send" if result is None else "missing_gotify_config")
        return
    message, summary_source = result
    limit = env_int("AGY_NOTIFY_MAX_CHARS", DEFAULT_MAX_CHARS, minimum=1)
    if summary_source and (summary := summarize(summary_source)):
        message = "Response finished: " + summary
    base, token = config
    sent = post_json(
        endpoint(base, "/message"),
        {"title": title(payload), "message": truncate(message, limit),
         "priority": env_int("AGY_NOTIFY_PRIORITY", 5, minimum=-10, maximum=10)},
        {"X-Gotify-Key": token, "User-Agent": USER_AGENT},
        env_int("AGY_NOTIFY_GOTIFY_TIMEOUT_SEC", 5, minimum=1, maximum=30), "gotify",
    )
    log("sent" if sent is not None else "delivery_failed", normalize_text(payload.get("terminationReason")))


def spawn_worker(raw: bytes) -> None:
    """Run `--worker` on the payload in a process that outlives the hook and holds none of
    agy's pipes."""
    command = [sys.executable, str(Path(__file__).resolve()), "--worker"]
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            # Out of a job agy may close (and so kill) when the hook exits, where allowed.
            worker = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB)
        except OSError:
            worker = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL, creationflags=flags)
    else:
        worker = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, start_new_session=True)
    assert worker.stdin is not None
    with worker.stdin:
        worker.stdin.write(raw)


def read_payload(raw: bytes) -> dict[str, object] | None:
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def main(arguments: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if arguments is None else arguments
    try:
        raw = sys.stdin.buffer.read()
    except OSError:
        raw = b""
    if "--worker" in arguments:
        payload = read_payload(raw)
        if payload is not None:
            deliver(payload)
        return 0
    # Only ever {}: agy acts on what a Stop hook prints, e.g. "decision": "continue".
    sys.stdout.write("{}\n")
    sys.stdout.flush()
    try:
        payload = read_payload(raw)
        if payload is not None and env_bool("GOTIFY_NOTIFY", True) \
                and event_message(payload) is not None and gotify_config() is not None:
            spawn_worker(raw)
    except Exception as error:  # the hook must never fail the turn
        log("hook_error", type(error).__name__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
