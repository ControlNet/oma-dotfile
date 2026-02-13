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
  CODEX_GOTIFY_NOTIFY_SUMMARIZER (format: "provider/model")
    - falls back to OPENCODE_GOTIFY_NOTIFY_SUMMARIZER
    - provider: anthropic | openai | azure-openai
  CODEX_NOTIFY_SUMMARIZER_TIMEOUT_SEC (default: 120)
  CODEX_NOTIFY_SUMMARIZER_MAX_INPUT_CHARS (default: 5000)
  CODEX_NOTIFY_SUMMARIZER_BASE_URL (optional override)
  CODEX_NOTIFY_SUMMARIZER_API_KEY (optional override)
  CODEX_NOTIFY_USER_AGENT (optional; default mimics browser UA)
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


def _parse_summarizer(raw: str) -> tuple[str, str] | None:
    if not raw or "/" not in raw:
        return None
    provider, model = raw.split("/", 1)
    provider = provider.strip()
    model = model.strip()
    if not provider or not model:
        return None
    return provider, model


def _get_summarizer_config() -> tuple[str, str] | None:
    raw = _env_first(
        "CODEX_GOTIFY_NOTIFY_SUMMARIZER",
        "OPENCODE_GOTIFY_NOTIFY_SUMMARIZER",
    )
    return _parse_summarizer(raw)


def _resolve_openai_endpoint(provider: str) -> tuple[str, str] | None:
    base_override = _env_first("CODEX_NOTIFY_SUMMARIZER_BASE_URL", "OPENCODE_NOTIFY_SUMMARIZER_BASE_URL")
    key_override = _env_first("CODEX_NOTIFY_SUMMARIZER_API_KEY", "OPENCODE_NOTIFY_SUMMARIZER_API_KEY")
    if base_override and key_override:
        return _normalize_base(base_override), key_override

    if provider == "openai":
        base = _env("OPENAI_BASE_URL", "https://api.openai.com/v1")
        key = _env("OPENAI_API_KEY")
        if base and key:
            return _normalize_base(base), key
        return None

    if provider == "azure-openai":
        base = _env("AZURE_OPENAI_BASE_URL")
        key = _env("AZURE_OPENAI_API_KEY")
        if base and key:
            return _normalize_base(base), key
        return None

    return None


def _resolve_anthropic_endpoint() -> tuple[str, str] | None:
    base_override = _env_first("CODEX_NOTIFY_SUMMARIZER_BASE_URL", "OPENCODE_NOTIFY_SUMMARIZER_BASE_URL")
    key_override = _env_first("CODEX_NOTIFY_SUMMARIZER_API_KEY", "OPENCODE_NOTIFY_SUMMARIZER_API_KEY")
    if base_override and key_override:
        return _normalize_base(base_override), key_override

    base = _env("ANTHROPIC_BASE_URL")
    key = _env("ANTHROPIC_AUTH_TOKEN")
    if not base or not key:
        return None

    normalized = _normalize_base(base)
    if not normalized.endswith("/v1"):
        normalized = normalized + "/v1"
    return normalized, key


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
    except (urllib.error.URLError, TimeoutError, OSError):
        return None

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        return data
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


def _extract_anthropic_text(response: dict[str, object]) -> str:
    content = response.get("content")
    if not isinstance(content, list):
        return ""
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") != "text":
            continue
        text = part.get("text")
        if isinstance(text, str) and text.strip():
            return _normalize_text(text)
    return ""


def _summarize_with_llm(text: str) -> str:
    summarizer = _get_summarizer_config()
    if not summarizer:
        return ""

    provider, model = summarizer
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
        return ""

    prompt = (
        "Summarize this in ONE short sentence (max 80 chars). "
        "No markdown, no quotes, just plain text:\n\n"
        f"{clipped}"
    )

    if provider == "anthropic":
        endpoint = _resolve_anthropic_endpoint()
        if not endpoint:
            return ""
        base_url, api_key = endpoint
        body = {
            "model": model,
            "max_tokens": 80,
            "system": "You are a concise summarizer. Output plain text only.",
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }
        data = _json_post(f"{base_url}/messages", body, headers, timeout_sec)
        if not data:
            return ""
        summary = _extract_anthropic_text(data)
        if not summary:
            return ""
        return _truncate(summary, 200)

    endpoint = _resolve_openai_endpoint(provider)
    if not endpoint:
        return ""
    base_url, api_key = endpoint
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "api-key": api_key,
    }

    responses_body = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": "You are a concise summarizer. Output plain text only.",
                    }
                ],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}],
            },
        ],
        "reasoning": {"effort": "low"},
        "max_output_tokens": 80,
    }
    responses_data = _json_post(
        f"{base_url}/responses",
        responses_body,
        headers,
        timeout_sec,
    )
    if responses_data:
        summary = _extract_openai_text(responses_data)
        if summary:
            return _truncate(summary, 200)

    chat_body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are a concise summarizer. Output plain text only.",
            },
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 80,
    }
    chat_data = _json_post(
        f"{base_url}/chat/completions",
        chat_body,
        headers,
        timeout_sec,
    )
    if not chat_data:
        return ""
    summary = _extract_openai_text(chat_data)
    if not summary:
        return ""
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
        ):
            if key in value:
                text = _extract_text_candidate(value[key])
                if text:
                    return text
    return ""


def _event_type(payload: dict[str, object]) -> str:
    raw = payload.get("type") or payload.get("event") or payload.get("hook_event_name")
    return str(raw or "").strip()


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

    if "subagent" in event_lower and ("stop" in event_lower or "complete" in event_lower):
        if notify_subagent:
            return "✅ Subagent task completed", ""
        return "", ""

    if event_lower == "agent-turn-complete" or ("turn" in event_lower and "complete" in event_lower):
        if notify_complete:
            assistant = str(payload.get("last-assistant-message") or "").strip()
            if assistant:
                preview = _preview(assistant, head, tail)
                return "✅ " + _escape_markdown(preview), assistant
            if include_prompt:
                prompts = payload.get("input-messages") or []
                if isinstance(prompts, list) and prompts:
                    last_prompt = _extract_text_candidate(prompts[-1])
                    if last_prompt:
                        preview = _preview(last_prompt, head, tail)
                        return "✅ " + _escape_markdown(preview), last_prompt
            return "✅ Agent turn completed", ""
        return "", ""

    tool_name = str(payload.get("tool_name") or payload.get("tool") or "").lower()
    if notify_question and tool_name == "question":
        question_text = _extract_text_candidate(payload.get("tool_input") or payload.get("args") or payload)
        if question_text:
            body = _preview(question_text, head, tail)
            return "❓ " + _escape_markdown(body), ""
        return "❓ Question", ""

    if include_prompt:
        prompt = _extract_text_candidate(payload.get("prompt") or payload.get("input-messages"))
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

    session_id = str(payload.get("session_id") or payload.get("conversation_id") or "")
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
        return 0

    gotify_url = _normalize_base(_env("GOTIFY_URL"))
    gotify_token = _env("GOTIFY_TOKEN_FOR_CODEX") or _env("GOTIFY_TOKEN_FOR_OPENCODE")
    if not gotify_url or not gotify_token:
        return 0

    include_prompt = _is_true(
        _env_first("CODEX_NOTIFY_INCLUDE_PROMPT", "OPENCODE_NOTIFY_INCLUDE_PROMPT", default="false")
    )
    message, summarize_source = _extract_message(payload, include_prompt)
    if not message:
        return 0

    if summarize_source:
        summary = _summarize_with_llm(summarize_source)
        if summary:
            message = "✅ " + _escape_markdown(summary)

    max_chars = _parse_int(
        _env_first("CODEX_NOTIFY_MAX_CHARS", "OPENCODE_NOTIFY_MAX_CHARS", default=str(DEFAULT_MAX_CHARS)),
        DEFAULT_MAX_CHARS,
    )
    if max_chars <= 0:
        max_chars = DEFAULT_MAX_CHARS
    if not _should_send(payload, message):
        return 0
    title = _env_first("CODEX_NOTIFY_TITLE", "OPENCODE_NOTIFY_TITLE", default="Codex")
    message = _truncate(message, max_chars)

    try:
        _push_gotify(gotify_url, gotify_token, title, message)
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
