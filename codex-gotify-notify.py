#!/usr/bin/env python3
"""
Codex notify hook that forwards events to Gotify.

Configure in ~/.codex/config.toml:
  notify = ["python3", "/absolute/path/to/.codex/codex-gotify-notify.py"]

Environment variables:
  GOTIFY_URL (required)
  GOTIFY_TOKEN_FOR_CODEX (required; falls back to GOTIFY_TOKEN_FOR_OPENCODE)

Optional:
  CODEX_NOTIFY_TITLE (default: "Codex")
  CODEX_NOTIFY_MAX_CHARS (default: 280)
  CODEX_NOTIFY_HEAD (default: 50)
  CODEX_NOTIFY_TAIL (default: 50)
  CODEX_NOTIFY_COMPLETE (default: true)
  CODEX_NOTIFY_SUBAGENT (default: false)
  CODEX_NOTIFY_PERMISSION (default: true)
  CODEX_NOTIFY_ERROR (default: true)
  CODEX_NOTIFY_QUESTION (default: true)
  CODEX_NOTIFY_INCLUDE_PROMPT (default: false)
  CODEX_NOTIFY_DEDUP_WINDOW_SEC (default: 15)
  GOTIFY_NOTIFY_SUMMARIZER_MODEL (e.g. "gpt-5-nano")
  GOTIFY_NOTIFY_SUMMARIZER_ENDPOINT (OpenAI-compatible, e.g. "https://api.openai.com/v1")
  GOTIFY_NOTIFY_SUMMARIZER_API_KEY
  CODEX_NOTIFY_SUMMARIZER_TIMEOUT_SEC (default: 120)
  CODEX_NOTIFY_SUMMARIZER_MAX_INPUT_CHARS (default: 5000)
  CODEX_NOTIFY_USER_AGENT (optional; default mimics browser UA)

Execution log:
  ~/.codex/log/gotify-notify.log
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_MAX_CHARS = 280
DEFAULT_HEAD = 50
DEFAULT_TAIL = 50
DEFAULT_SUMMARIZER_TIMEOUT_SEC = 120.0
DEFAULT_SUMMARIZER_MAX_INPUT_CHARS = 5000
DEFAULT_DEDUP_WINDOW_SEC = 15
DEFAULT_THREAD_SOURCE_CACHE_MAX_ENTRIES = 512
NOTIFY_LOG_FILE = Path.home() / ".codex" / "log" / "gotify-notify.log"


def _log_line(message: str) -> None:
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())
    line = f"{timestamp} pid={os.getpid()} {message}\n"
    try:
        NOTIFY_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with NOTIFY_LOG_FILE.open("a", encoding="utf-8") as fp:
            fp.write(line)
    except OSError:
        return


def _log_preview(value: object, limit: int = 300) -> str:
    return _truncate(_normalize_text(str(value or "")), limit)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_first(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name)
        if value is not None:
            return value.strip()
    return default


def _notify_user_agent() -> str:
    custom = _env_first("CODEX_NOTIFY_USER_AGENT", "OPENCODE_NOTIFY_USER_AGENT")
    if custom:
        return custom
    # Some reverse proxies/WAFs block Python's default urllib user agent.
    return "Mozilla/5.0 (X11; Linux x86_64) CodexGotifyNotify/1.0"


def _normalize_base(url: str) -> str:
    return url[:-1] if url.endswith("/") else url


def _truncate(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3] + "..."


def _normalize_text(text: str) -> str:
    return " ".join(str(text).split())


def _preview(text: str, head: int, tail: int) -> str:
    normalized = _normalize_text(text)
    if not normalized:
        return ""
    if head <= 0 and tail <= 0:
        return normalized
    if head < 0:
        head = 0
    if tail < 0:
        tail = 0
    if len(normalized) <= head + tail + 3:
        return normalized
    if tail == 0:
        return normalized[:head]
    if head == 0:
        return normalized[-tail:]
    return f"{normalized[:head]}...{normalized[-tail:]}"


def _escape_markdown(text: str) -> str:
    escape_set = {
        "\\",
        "`",
        "*",
        "_",
        "~",
        "[",
        "]",
        "(",
        ")",
        "#",
        "+",
        "-",
        ".",
        "!",
        ">",
        "|",
        "{",
        "}",
    }
    out = []
    for ch in str(text):
        if ch in escape_set:
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def _parse_int(raw: str, fallback: int) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return fallback


def _parse_float(raw: str, fallback: float) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return fallback


def _is_true(raw: str) -> bool:
    return raw.lower() in {"1", "true", "yes", "on"}


def _get_summarizer_config() -> tuple[str, str, str] | None:
    model = _env("GOTIFY_NOTIFY_SUMMARIZER_MODEL")
    endpoint = _normalize_base(_env("GOTIFY_NOTIFY_SUMMARIZER_ENDPOINT"))
    api_key = _env("GOTIFY_NOTIFY_SUMMARIZER_API_KEY")
    if not model or not endpoint or not api_key:
        missing: list[str] = []
        if not model:
            missing.append("GOTIFY_NOTIFY_SUMMARIZER_MODEL")
        if not endpoint:
            missing.append("GOTIFY_NOTIFY_SUMMARIZER_ENDPOINT")
        if not api_key:
            missing.append("GOTIFY_NOTIFY_SUMMARIZER_API_KEY")
        _log_line(f"summarizer_config_missing missing={','.join(missing)}")
        return None
    return model, endpoint, api_key


def _join_endpoint(base_url: str, path: str) -> str:
    if base_url.endswith(path):
        return base_url
    return f"{base_url}{path}"


def _json_post(
    url: str,
    body: dict[str, object],
    headers: dict[str, str],
    timeout_sec: float,
) -> dict[str, object] | None:
    request_data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request_headers = dict(headers)
    request_headers.setdefault("User-Agent", _notify_user_agent())
    req = urllib.request.Request(
        url,
        data=request_data,
        headers=request_headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except OSError:
            detail = ""
        _log_line(f"http_error url={url} status={exc.code} detail={_log_preview(detail)}")
        return None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        _log_line(f"request_error url={url} kind={type(exc).__name__} detail={_log_preview(exc)}")
        return None

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        _log_line(f"json_decode_error url={url} body={_log_preview(payload)}")
        return None
    if isinstance(data, dict):
        return data
    _log_line(f"unexpected_json_type url={url} kind={type(data).__name__}")
    return None


def _extract_openai_text(response: dict[str, object]) -> str:
    output_text = response.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return _normalize_text(output_text)

    output = response.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    return _normalize_text(text)

    choices = response.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return _normalize_text(content)

    return ""


def _summarize_with_llm(text: str) -> str:
    summarizer = _get_summarizer_config()
    if not summarizer:
        _log_line("summarizer_skip reason=missing_summarizer_env")
        return ""

    model, base_url, api_key = summarizer
    _log_line(f"summarizer_start model={model} endpoint={base_url}")
    timeout_sec = _parse_float(
        _env_first(
            "CODEX_NOTIFY_SUMMARIZER_TIMEOUT_SEC",
            "OPENCODE_NOTIFY_SUMMARIZER_TIMEOUT_SEC",
            default=str(DEFAULT_SUMMARIZER_TIMEOUT_SEC),
        ),
        DEFAULT_SUMMARIZER_TIMEOUT_SEC,
    )
    if timeout_sec <= 0:
        timeout_sec = DEFAULT_SUMMARIZER_TIMEOUT_SEC

    max_input_chars = _parse_int(
        _env_first(
            "CODEX_NOTIFY_SUMMARIZER_MAX_INPUT_CHARS",
            "OPENCODE_NOTIFY_SUMMARIZER_MAX_INPUT_CHARS",
            default=str(DEFAULT_SUMMARIZER_MAX_INPUT_CHARS),
        ),
        DEFAULT_SUMMARIZER_MAX_INPUT_CHARS,
    )
    if max_input_chars <= 0:
        max_input_chars = DEFAULT_SUMMARIZER_MAX_INPUT_CHARS

    clipped = _truncate(_normalize_text(text), max_input_chars)
    if not clipped:
        _log_line("summarizer_skip reason=empty_input")
        return ""

    prompt = (
        "You are a concise summarizer. Output plain text only.\n"
        "Summarize this in ONE short sentence (max 80 chars). "
        "No markdown, no quotes, just plain text:\n\n"
        f"{clipped}"
    )

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "api-key": api_key,
    }

    chat_body = {
        "model": model,
        "messages": [
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 80,
    }
    chat_data = _json_post(
        _join_endpoint(base_url, "/chat/completions"),
        chat_body,
        headers,
        timeout_sec,
    )
    if chat_data:
        summary = _extract_openai_text(chat_data)
        if summary:
            _log_line("summarizer_success route=chat_completions")
            return _truncate(summary, 200)
    _log_line("summarizer_fallback route=responses reason=chat_completions_failed_or_empty")

    responses_body = {
        "model": model,
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}],
            },
        ],
        "reasoning": {"effort": "low"},
        "max_output_tokens": 80,
    }
    responses_data = _json_post(
        _join_endpoint(base_url, "/responses"),
        responses_body,
        headers,
        timeout_sec,
    )
    if not responses_data:
        _log_line("summarizer_failed reason=responses_failed")
        return ""
    summary = _extract_openai_text(responses_data)
    if not summary:
        _log_line("summarizer_failed reason=responses_empty_output")
        return ""
    _log_line("summarizer_success route=responses")
    return _truncate(summary, 200)


def _extract_text_candidate(value: object) -> str:
    if isinstance(value, str):
        return _normalize_text(value)
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            text = _extract_text_candidate(item)
            if text:
                parts.append(text)
        return _normalize_text(" ".join(parts))
    if isinstance(value, dict):
        for key in (
            "last-assistant-message",
            "last_assistant_message",
            "input-messages",
            "input_messages",
            "message",
            "content",
            "text",
            "assistant_message",
            "assistant_response",
            "output_text",
            "output",
            "response",
            "result",
            "reason",
            "summary",
            "prompt",
            "error",
            "hook_event",
        ):
            if key in value:
                text = _extract_text_candidate(value[key])
                if text:
                    return text
    return ""


def _payload_get(container: object, *keys: str) -> object:
    if not isinstance(container, dict):
        return None
    for key in keys:
        variants = (key, key.replace("_", "-"), key.replace("-", "_"))
        for variant in variants:
            if variant in container:
                return container[variant]
    return None


def _hook_event_payload(payload: dict[str, object]) -> dict[str, object] | None:
    hook_event = _payload_get(payload, "hook_event")
    if isinstance(hook_event, dict):
        return hook_event
    return None


def _payload_thread_id(payload: dict[str, object]) -> str:
    thread_id = _payload_get(payload, "thread_id", "thread-id")
    if thread_id is None:
        hook_event = _hook_event_payload(payload)
        thread_id = _payload_get(hook_event, "thread_id", "thread-id")
    text = str(thread_id or "").strip()
    return text


def _payload_session_id(payload: dict[str, object]) -> str:
    session_id = _payload_get(
        payload,
        "session_id",
        "conversation_id",
        "thread_id",
        "thread-id",
    )
    if session_id is None:
        hook_event = _hook_event_payload(payload)
        session_id = _payload_get(hook_event, "thread_id", "thread-id")
    text = str(session_id or "").strip()
    return text


def _payload_last_assistant_message(payload: dict[str, object]) -> str:
    value = _payload_get(payload, "last_assistant_message", "last-assistant-message")
    if value is None:
        hook_event = _hook_event_payload(payload)
        value = _payload_get(hook_event, "last_assistant_message", "last-assistant-message")
    return _normalize_text(str(value or ""))


def _payload_input_messages(payload: dict[str, object]) -> list[object]:
    value = _payload_get(payload, "input_messages", "input-messages")
    if value is None:
        hook_event = _hook_event_payload(payload)
        value = _payload_get(hook_event, "input_messages", "input-messages")
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _event_type(payload: dict[str, object]) -> str:
    raw = _payload_get(payload, "type", "event", "hook_event_name")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()

    hook_event = _hook_event_payload(payload)
    event_type = _payload_get(hook_event, "event_type", "type")
    normalized = str(event_type or "").strip().lower().replace("_", "-")
    if normalized == "after-agent":
        return "agent-turn-complete"
    if normalized:
        return normalized
    return ""


def _thread_source_cache_path() -> Path:
    return Path.home() / ".codex" / ".gotify-notify-thread-source-cache.json"


def _sessions_root_path() -> Path:
    custom = _env("CODEX_NOTIFY_SESSIONS_DIR")
    if custom:
        return Path(custom).expanduser()
    return Path.home() / ".codex" / "sessions"


def _load_thread_source_cache() -> dict[str, bool]:
    path = _thread_source_cache_path()
    try:
        if not path.exists():
            return {}
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            return {}
    except (OSError, json.JSONDecodeError):
        return {}

    out: dict[str, bool] = {}
    for key, value in data.items():
        if not isinstance(key, str):
            continue
        if isinstance(value, bool):
            out[key] = value
        elif isinstance(value, dict) and isinstance(value.get("is_subagent"), bool):
            out[key] = value["is_subagent"]
    return out


def _save_thread_source_cache(cache: dict[str, bool]) -> None:
    path = _thread_source_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if len(cache) > DEFAULT_THREAD_SOURCE_CACHE_MAX_ENTRIES:
            keys = list(cache.keys())
            overflow = len(cache) - DEFAULT_THREAD_SOURCE_CACHE_MAX_ENTRIES
            for key in keys[:overflow]:
                cache.pop(key, None)
        path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except OSError:
        return


def _source_is_subagent(source: object) -> bool:
    if isinstance(source, dict):
        for key in ("subagent", "sub_agent", "thread_spawn", "threadSpawn"):
            if key in source:
                return True
        for value in source.values():
            if _source_is_subagent(value):
                return True
        return False
    if isinstance(source, list):
        return any(_source_is_subagent(item) for item in source)
    if isinstance(source, str):
        normalized = source.lower().replace("_", "-")
        return "subagent" in normalized or "sub-agent" in normalized or "thread-spawn" in normalized
    return False


def _detect_subagent_from_sessions(thread_id: str) -> bool | None:
    sessions_root = _sessions_root_path()
    if not sessions_root.exists():
        return None

    candidates = list(sessions_root.glob(f"**/rollout-*-{thread_id}.jsonl"))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item.stat().st_mtime, reverse=True)

    for file_path in candidates[:3]:
        try:
            with file_path.open("r", encoding="utf-8") as fp:
                first_line = fp.readline().strip()
            if not first_line:
                continue
            parsed = json.loads(first_line)
            if not isinstance(parsed, dict):
                continue
            payload = parsed.get("payload")
            if not isinstance(payload, dict):
                continue
            source = _payload_get(payload, "source")
            if source is None:
                continue
            return _source_is_subagent(source)
        except (OSError, json.JSONDecodeError):
            continue
    return None


def _is_subagent_thread(thread_id: str) -> bool:
    thread_id = thread_id.strip()
    if not thread_id:
        return False

    cache = _load_thread_source_cache()
    if thread_id in cache:
        if cache[thread_id]:
            _log_line(f"subagent_detected source=cache thread_id={thread_id}")
        return cache[thread_id]

    detected = _detect_subagent_from_sessions(thread_id)
    if detected is None:
        return False

    cache[thread_id] = detected
    _save_thread_source_cache(cache)
    if detected:
        _log_line(f"subagent_detected source=sessions thread_id={thread_id}")
    return detected


def _is_true_like(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return _is_true(value.strip())
    return False


def _looks_like_subagent_text(value: object) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.strip().lower().replace("_", "-")
    return "subagent" in normalized or "sub-agent" in normalized or "child" in normalized


def _has_parent_reference(container: dict[str, object]) -> bool:
    for key in (
        "parent_id",
        "parentID",
        "parentId",
        "parent_session_id",
        "parentSessionID",
        "parentSessionId",
        "parent_session",
        "parentSession",
        "parent",
    ):
        if key not in container:
            continue
        value = container.get(key)
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, (int, float)) and value != 0:
            return True
        if isinstance(value, dict) and value:
            return True
    return False


def _is_subagent_event(payload: dict[str, object], event_lower: str) -> bool:
    if _looks_like_subagent_text(event_lower):
        return True

    thread_id = _payload_thread_id(payload)
    if thread_id and _is_subagent_thread(thread_id):
        return True

    session_id = _payload_session_id(payload)
    if thread_id and session_id and thread_id != session_id:
        return True

    containers: list[dict[str, object]] = [payload]
    hook_event = _hook_event_payload(payload)
    if hook_event is not None:
        containers.append(hook_event)
    for key in ("properties", "session", "metadata", "data", "source"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            containers.append(nested)

    for container in containers:
        if _has_parent_reference(container):
            return True

        for key in (
            "is_subagent",
            "isSubagent",
            "is_sub_agent",
            "subagent",
            "sub_agent",
            "is_child",
            "isChild",
            "is_child_session",
            "isChildSession",
            "child_session",
            "childSession",
        ):
            if key in container and _is_true_like(container.get(key)):
                return True

        for key in (
            "session_type",
            "sessionType",
            "agent_type",
            "agentType",
            "kind",
            "source",
        ):
            if key in container and _looks_like_subagent_text(container.get(key)):
                return True

    return False


def _extract_message(payload: dict[str, object], include_prompt: bool) -> tuple[str, str]:
    event_type = _event_type(payload)
    event_lower = event_type.lower()

    head = _parse_int(_env_first("CODEX_NOTIFY_HEAD", "OPENCODE_NOTIFY_HEAD", default=str(DEFAULT_HEAD)), DEFAULT_HEAD)
    tail = _parse_int(_env_first("CODEX_NOTIFY_TAIL", "OPENCODE_NOTIFY_TAIL", default=str(DEFAULT_TAIL)), DEFAULT_TAIL)
    notify_complete = _is_true(_env_first("CODEX_NOTIFY_COMPLETE", "OPENCODE_NOTIFY_COMPLETE", default="true"))
    notify_subagent = _is_true(_env_first("CODEX_NOTIFY_SUBAGENT", "OPENCODE_NOTIFY_SUBAGENT", default="false"))
    notify_permission = _is_true(_env_first("CODEX_NOTIFY_PERMISSION", "OPENCODE_NOTIFY_PERMISSION", default="true"))
    notify_error = _is_true(_env_first("CODEX_NOTIFY_ERROR", "OPENCODE_NOTIFY_ERROR", default="true"))
    notify_question = _is_true(_env_first("CODEX_NOTIFY_QUESTION", "OPENCODE_NOTIFY_QUESTION", default="true"))
    is_subagent = _is_subagent_event(payload, event_lower)

    if "permission" in event_lower and ("ask" in event_lower or "request" in event_lower):
        if notify_permission:
            return "🔐 Permission request", ""
        return "", ""

    if "error" in event_lower:
        if notify_error:
            error_text = _extract_text_candidate(payload.get("error") or payload)
            if "aborted" in error_text.lower():
                return "", ""
            return "❌ Session encountered an error", ""
        return "", ""

    if is_subagent and ("stop" in event_lower or "complete" in event_lower):
        if notify_subagent:
            return "✅ Subagent task completed", ""
        return "", ""

    if event_lower == "agent-turn-complete" or ("turn" in event_lower and "complete" in event_lower):
        if is_subagent:
            if notify_subagent:
                return "✅ Subagent task completed", ""
            return "", ""
        if notify_complete:
            assistant = _payload_last_assistant_message(payload)
            if assistant:
                preview = _preview(assistant, head, tail)
                return "✅ " + _escape_markdown(preview), assistant
            if include_prompt:
                prompts = _payload_input_messages(payload)
                if prompts:
                    last_prompt = _extract_text_candidate(prompts[-1])
                    if last_prompt:
                        preview = _preview(last_prompt, head, tail)
                        return "✅ " + _escape_markdown(preview), last_prompt
            return "✅ Agent turn completed", ""
        return "", ""

    tool_name = str(_payload_get(payload, "tool_name", "tool") or "").lower()
    if not tool_name:
        hook_event = _hook_event_payload(payload)
        tool_name = str(_payload_get(hook_event, "tool_name", "tool") or "").lower()
    if notify_question and tool_name == "question":
        question_text = _extract_text_candidate(_payload_get(payload, "tool_input", "args") or payload)
        if question_text:
            body = _preview(question_text, head, tail)
            return "❓ " + _escape_markdown(body), ""
        return "❓ Question", ""

    if include_prompt:
        prompt = _extract_text_candidate(_payload_get(payload, "prompt") or _payload_input_messages(payload))
        if prompt:
            preview = _preview(prompt, head, tail)
            return "✅ " + _escape_markdown(preview), ""

    return "", ""


def _dedup_cache_path() -> Path:
    return Path.home() / ".codex" / ".gotify-notify-cache.json"


def _should_send(payload: dict[str, object], message: str) -> bool:
    dedup_window_sec = _parse_int(
        _env_first(
            "CODEX_NOTIFY_DEDUP_WINDOW_SEC",
            "OPENCODE_NOTIFY_DEDUP_WINDOW_SEC",
            default=str(DEFAULT_DEDUP_WINDOW_SEC),
        ),
        DEFAULT_DEDUP_WINDOW_SEC,
    )
    if dedup_window_sec <= 0:
        return True

    session_id = _payload_session_id(payload)
    event = _event_type(payload)
    dedup_key = f"{session_id}|{event}|{message}"
    now = int(time.time())
    cache_path = _dedup_cache_path()
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        if cache_path.exists():
            raw = cache_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if not isinstance(data, dict):
                data = {}
        else:
            data = {}
    except (OSError, json.JSONDecodeError):
        data = {}

    last = data.get(dedup_key)
    if isinstance(last, int) and now - last < dedup_window_sec:
        _log_line(f"dedup_skip key={_log_preview(dedup_key, 180)} age_sec={now - last}")
        return False

    compacted: dict[str, int] = {}
    for key, value in data.items():
        if isinstance(key, str) and isinstance(value, int) and now - value < dedup_window_sec:
            compacted[key] = value
    compacted[dedup_key] = now
    try:
        cache_path.write_text(json.dumps(compacted, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return True


def _push_gotify(base_url: str, token: str, title: str, message: str) -> None:
    body = json.dumps(
        {"title": title, "message": message, "priority": 5},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/message",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Gotify-Key": token,
            "User-Agent": _notify_user_agent(),
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10):
        return


def main() -> int:
    _log_line("run_start")
    payload: dict[str, object] | None = None
    if len(sys.argv) >= 2:
        payload_raw = sys.argv[-1]
        try:
            parsed = json.loads(payload_raw)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            payload = parsed

    if payload is None:
        try:
            raw = sys.stdin.read().strip()
        except OSError:
            raw = ""
        if raw:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                payload = parsed

    if not isinstance(payload, dict):
        _log_line("run_skip reason=invalid_payload")
        return 0

    event_type = _event_type(payload) or "unknown"
    thread_id = _payload_thread_id(payload) or _payload_session_id(payload) or "-"
    _log_line(f"payload_loaded event={event_type} thread_id={thread_id}")

    gotify_url = _normalize_base(_env("GOTIFY_URL"))
    gotify_token = _env("GOTIFY_TOKEN_FOR_CODEX") or _env("GOTIFY_TOKEN_FOR_OPENCODE")
    if not gotify_url or not gotify_token:
        _log_line("run_skip reason=missing_gotify_config")
        return 0

    include_prompt = _is_true(
        _env_first("CODEX_NOTIFY_INCLUDE_PROMPT", "OPENCODE_NOTIFY_INCLUDE_PROMPT", default="false")
    )
    message, summarize_source = _extract_message(payload, include_prompt)
    if not message:
        _log_line(f"run_skip reason=no_message event={event_type}")
        return 0

    if summarize_source:
        _log_line(f"summarizer_attempt input_chars={len(summarize_source)}")
        summary = _summarize_with_llm(summarize_source)
        if summary:
            message = "✅ " + _escape_markdown(summary)
            _log_line("summarizer_applied")
        else:
            _log_line("summarizer_failed fallback=preview")
    else:
        _log_line("summarizer_skip reason=empty_source")

    max_chars = _parse_int(
        _env_first("CODEX_NOTIFY_MAX_CHARS", "OPENCODE_NOTIFY_MAX_CHARS", default=str(DEFAULT_MAX_CHARS)),
        DEFAULT_MAX_CHARS,
    )
    if max_chars <= 0:
        max_chars = DEFAULT_MAX_CHARS
    if not _should_send(payload, message):
        _log_line("run_skip reason=dedup")
        return 0
    title = _env_first("CODEX_NOTIFY_TITLE", "OPENCODE_NOTIFY_TITLE", default="Codex")
    message = _truncate(message, max_chars)

    try:
        _push_gotify(gotify_url, gotify_token, title, message)
        _log_line(f"run_success event={event_type} message_chars={len(message)}")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        _log_line(f"gotify_push_failed kind={type(exc).__name__} detail={_log_preview(exc)}")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
