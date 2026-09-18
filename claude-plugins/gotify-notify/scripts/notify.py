#!/usr/bin/env python3
"""Forward selected Claude Code hook events to Gotify."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys
import time
import urllib.error
import urllib.request

DEFAULT_MAX_CHARS = 280
DEFAULT_HEAD = 80
DEFAULT_TAIL = 80
DEFAULT_DEDUP_WINDOW_SEC = 15
MAX_LOG_BYTES = 256 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024


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
    head = env_int("CLAUDE_NOTIFY_HEAD", DEFAULT_HEAD)
    tail = env_int("CLAUDE_NOTIFY_TAIL", DEFAULT_TAIL)
    if len(text) <= head + tail + 3:
        return text
    if not head:
        return text[-tail:] if tail else ""
    if not tail:
        return text[:head]
    return text[:head] + "..." + text[-tail:]


def config_dir() -> Path:
    custom = env("CLAUDE_CONFIG_DIR")
    return Path(custom).expanduser() if custom else Path.home() / ".claude"


def log_path() -> Path:
    custom = env("CLAUDE_NOTIFY_LOG_FILE")
    return Path(custom).expanduser() if custom else config_dir() / "logs" / "gotify-notify.log"


def log(stage: str, detail: str = "") -> None:
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size >= MAX_LOG_BYTES:
            rotated = path.with_name(path.name + ".1")
            if rotated.exists():
                rotated.unlink()
            path.replace(rotated)
        safe_stage = truncate(normalize_text(stage), 48)
        safe_detail = truncate(normalize_text(detail), 160)
        suffix = f" {safe_detail}" if safe_detail else ""
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {safe_stage}{suffix}\n")
    except OSError:
        pass


def state_path() -> Path:
    return config_dir() / "gotify-notify" / "state.sqlite3"


def dedup_window() -> int:
    return env_int("CLAUDE_NOTIFY_DEDUP_WINDOW_SEC", DEFAULT_DEDUP_WINDOW_SEC)


def claim(key: str) -> bool:
    window = dedup_window()
    if window <= 0:
        return True
    now = int(time.time())
    path = state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path, timeout=2) as database:
            database.execute(
                "CREATE TABLE IF NOT EXISTS notifications "
                "(key TEXT PRIMARY KEY, state TEXT NOT NULL, created_at INTEGER NOT NULL)"
            )
            database.execute(
                "DELETE FROM notifications WHERE "
                "(state = 'sent' AND created_at < ?) OR "
                "(state = 'pending' AND created_at < ?)",
                (now - window, now - max(60, window * 4)),
            )
            try:
                database.execute(
                    "INSERT INTO notifications (key, state, created_at) VALUES (?, 'pending', ?)",
                    (key, now),
                )
            except sqlite3.IntegrityError:
                return False
        return True
    except (OSError, sqlite3.Error) as error:
        log("dedup_error", type(error).__name__)
        return True


def finish(key: str, sent: bool) -> None:
    if dedup_window() <= 0:
        return
    try:
        with sqlite3.connect(state_path(), timeout=2) as database:
            if sent:
                database.execute(
                    "UPDATE notifications SET state = 'sent', created_at = ? WHERE key = ?",
                    (int(time.time()), key),
                )
            else:
                database.execute("DELETE FROM notifications WHERE key = ?", (key,))
    except (OSError, sqlite3.Error) as error:
        log("dedup_finish_error", type(error).__name__)


def normalize_base(url: str) -> str:
    return url.rstrip("/")


def endpoint(base: str, suffix: str) -> str:
    return base if base.endswith(suffix) else base + suffix


def post_json(
    url: str, body: dict[str, object], headers: dict[str, str], timeout: int, stage: str
) -> dict[str, object] | None:
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
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
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    text = normalize_text(part["text"])
                    if text:
                        return text
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
    model = env("GOTIFY_NOTIFY_SUMMARIZER_MODEL")
    base = normalize_base(env("GOTIFY_NOTIFY_SUMMARIZER_ENDPOINT"))
    api_key = env("GOTIFY_NOTIFY_SUMMARIZER_API_KEY")
    if not model or not base or not api_key:
        return ""
    clipped = truncate(
        normalize_text(text),
        env_int("CLAUDE_NOTIFY_SUMMARIZER_MAX_INPUT_CHARS", 5000, minimum=1),
    )
    if not clipped:
        return ""
    prompt = (
        "Output plain text only. Use the same language as the input. "
        "Summarize the completed response in one short sentence of at most 80 characters.\n\n"
        + clipped
    )
    headers = {
        "Authorization": f"Bearer {api_key}",
        "api-key": api_key,
        "User-Agent": "ClaudeCodeGotifyNotify/1.0",
    }
    timeout = env_int("CLAUDE_NOTIFY_SUMMARIZER_TIMEOUT_SEC", 8, minimum=1, maximum=8)
    chat = post_json(
        endpoint(base, "/chat/completions"),
        {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 80},
        headers, timeout, "summarizer_chat",
    )
    if chat is not None:
        result = extract_model_text(chat)
        if result:
            return truncate(result, 200)
    responses = post_json(
        endpoint(base, "/responses"),
        {
            "model": model,
            "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            "reasoning": {"effort": "low"},
            "max_output_tokens": 80,
        },
        headers, timeout, "summarizer_responses",
    )
    return truncate(extract_model_text(responses or {}), 200)


def gotify_config() -> tuple[str, str] | None:
    base = normalize_base(env("GOTIFY_URL"))
    token = env_first(
        "GOTIFY_TOKEN_FOR_CLAUDE",
        "GOTIFY_TOKEN_FOR_OPENCODE",
        "GOTIFY_TOKEN_FOR_CODEX",
        "GOTIFY_TOKEN_FOR_OMP",
    )
    return (base, token) if base and token else None


def title(payload: dict[str, object]) -> str:
    custom = env("CLAUDE_NOTIFY_TITLE")
    if custom:
        return custom
    cwd = normalize_text(payload.get("cwd"))
    project = Path(cwd).name if cwd else "unknown-project"
    return f"Claude Code :: {project}@{socket.gethostname() or 'unknown-host'}"


def question_text(tool_input: object) -> str:
    if not isinstance(tool_input, dict):
        return ""
    questions = tool_input.get("questions")
    if not isinstance(questions, list):
        return ""
    parts: list[str] = []
    for question in questions[:3]:
        if not isinstance(question, dict):
            continue
        text = normalize_text(question.get("question") or question.get("header"))
        if text:
            parts.append(text)
    return " / ".join(parts)


def has_pending_work(payload: dict[str, object]) -> bool:
    tasks = payload.get("background_tasks")
    crons = payload.get("session_crons")
    return bool(isinstance(tasks, list) and tasks) or bool(isinstance(crons, list) and crons)


def event_message(payload: dict[str, object]) -> tuple[str, str] | None:
    event = payload.get("hook_event_name")
    if not isinstance(event, str):
        return None
    is_subagent = bool(payload.get("agent_id"))

    if event == "Stop":
        if is_subagent or not env_bool("CLAUDE_NOTIFY_COMPLETE", True) or has_pending_work(payload):
            return None
        response = normalize_text(payload.get("last_assistant_message"))
        if not response:
            return None
        return "Response finished: " + preview(response), response

    if event == "StopFailure":
        if is_subagent or not env_bool("CLAUDE_NOTIFY_ERROR", True):
            return None
        error = normalize_text(payload.get("error") or payload.get("last_assistant_message"))
        return ("API error: " + (error or "unknown"), "")

    if event == "Notification":
        notification_type = payload.get("notification_type")
        detail = normalize_text(payload.get("message"))
        if notification_type == "permission_prompt" and env_bool("CLAUDE_NOTIFY_PERMISSION", True):
            return "Permission needed" + (f": {detail}" if detail else ""), ""
        if notification_type in {"elicitation_dialog", "elicitation_url_dialog", "agent_needs_input"} and env_bool("CLAUDE_NOTIFY_QUESTION", True):
            return "Input needed" + (f": {detail}" if detail else ""), ""
        return None

    if event == "PreToolUse":
        if is_subagent or payload.get("tool_name") != "AskUserQuestion" or not env_bool("CLAUDE_NOTIFY_QUESTION", True):
            return None
        question = question_text(payload.get("tool_input"))
        return ("Question" + (f": {question}" if question else ""), "")

    if event == "SubagentStop" and env_bool("CLAUDE_NOTIFY_SUBAGENT", False):
        response = normalize_text(payload.get("last_assistant_message"))
        return "Subagent finished" + (f": {preview(response)}" if response else ""), response

    return None


def dedup_key(payload: dict[str, object], message: str) -> str:
    identity = payload.get("prompt_id") or payload.get("tool_use_id") or message
    raw = "|".join((
        normalize_text(payload.get("session_id")),
        normalize_text(payload.get("hook_event_name")),
        normalize_text(identity),
        message,
    ))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def push_gotify(payload: dict[str, object], message: str) -> bool:
    config = gotify_config()
    if config is None:
        return False
    base, token = config
    result = post_json(
        endpoint(base, "/message"),
        {
            "title": title(payload),
            "message": message,
            "priority": env_int("CLAUDE_NOTIFY_PRIORITY", 5, minimum=-10, maximum=10),
        },
        {"X-Gotify-Key": token, "User-Agent": "ClaudeCodeGotifyNotify/1.0"},
        env_int("CLAUDE_NOTIFY_GOTIFY_TIMEOUT_SEC", 5, minimum=1, maximum=5),
        "gotify",
    )
    return result is not None


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--dry-run", action="store_true")
    options, _ = parser.parse_known_args(arguments)
    try:
        payload = json.load(sys.stdin)
    except (OSError, json.JSONDecodeError):
        return 0
    if not isinstance(payload, dict):
        return 0
    result = event_message(payload)
    if result is None:
        return 0
    message, summary_source = result
    message = truncate(message, env_int("CLAUDE_NOTIFY_MAX_CHARS", DEFAULT_MAX_CHARS, minimum=1))
    if options.dry_run:
        print(json.dumps({"title": title(payload), "message": message}, ensure_ascii=False))
        return 0
    if gotify_config() is None:
        log("skip", "missing_gotify_config")
        return 0
    key = dedup_key(payload, message)
    if not claim(key):
        log("skip", "deduplicated")
        return 0
    if summary_source:
        summary = summarize(summary_source)
        if summary:
            prefix = "Subagent finished: " if payload.get("hook_event_name") == "SubagentStop" else "Response finished: "
            message = truncate(prefix + summary, env_int("CLAUDE_NOTIFY_MAX_CHARS", DEFAULT_MAX_CHARS, minimum=1))
    sent = push_gotify(payload, message)
    finish(key, sent)
    log("sent" if sent else "delivery_failed", normalize_text(payload.get("hook_event_name")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
