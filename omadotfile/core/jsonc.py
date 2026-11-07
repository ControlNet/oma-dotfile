"""Read JSONC (JSON with comments and trailing commas) and edit it as text."""

import json
from pathlib import Path
import re
from typing import Any, cast


# Keep JSON strings intact while accepting JSONC comments and trailing commas.
JSONC_TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/', re.DOTALL)


def read_jsonc_object(path: Path) -> dict:
    try:
        return loads_jsonc_object(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"{exc} in {path}") from exc


def loads_jsonc_object(text: str) -> dict[str, Any]:
    """Parse JSONC text that must hold a JSON object; ValueError otherwise."""
    content = JSONC_TOKEN.sub(
        lambda match: match.group() if match.group().startswith('"') else " ",
        text,
    )
    content = re.sub(
        r'"(?:\\.|[^"\\])*"|,\s*(?=[}\]])',
        lambda match: match.group() if match.group().startswith('"') else "",
        content,
    )
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return cast(dict[str, Any], value)


def merge_config_objects(base: dict, override: dict) -> dict:
    """Merge legacy JSON and JSONC provider objects in load order."""
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_config_objects(result[key], value)
        else:
            result[key] = value
    return result


JSONC_STRUCTURE_TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/|[{}]', re.DOTALL)


def find_jsonc_top_level_object(content: str, key: str) -> tuple[int, int] | None:
    """Return the span of a top-level member's object value, skipping strings and comments."""
    quoted_key = json.dumps(key)
    depth = 0
    armed = False
    start = None
    for match in JSONC_STRUCTURE_TOKEN.finditer(content):
        token = match.group()
        if token == "{":
            depth += 1
            if armed and depth == 2:
                start, armed = match.start(), False
        elif token == "}":
            depth -= 1
            if start is not None and depth == 1:
                return start, match.end()
        elif depth == 1 and start is None:
            armed = token == quoted_key
    return None


def rewrite_model_prefix(content: str, prefix: str) -> str:
    """Point every `"codex/<model>"` string at another provider, keeping the model ids."""
    return JSONC_TOKEN.sub(
        lambda match: match.group().replace('"codex/', f'"{prefix}/', 1)
        if match.group().startswith('"codex/') else match.group(),
        content,
    )
