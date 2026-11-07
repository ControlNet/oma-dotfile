"""Edit TOML files line by line, keeping comments and layout.

tomllib (Python 3.11+) only reads TOML, and Python 3.10 has none at all, so edits are made on
the lines themselves. When tomllib is there it checks values and results; without it, small
scanners do the same job for the common cases.
"""

import json
import re

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11; fall back to the small scanners below.
    tomllib = None


# One bare or quoted key part; dotted keys join them with optional spaces.
TOML_KEY_PART = r"""(?:[A-Za-z0-9_-]+|"(?:[^"\\]|\\.)*"|'[^']*')"""


TOML_DOTTED_KEY = rf"{TOML_KEY_PART}(?:\s*\.\s*{TOML_KEY_PART})*"


# A header may carry a trailing comment: `[profiles.work] # note` is valid TOML.
TOML_TABLE_HEADER = re.compile(rf"^\s*\[\[?\s*({TOML_DOTTED_KEY})\s*\]\]?\s*(?:#.*)?$")


TOML_ASSIGNMENT_START = re.compile(rf"^\s*({TOML_DOTTED_KEY})\s*=(.*)$")


def toml_key_name(raw: str) -> str:
    """Normalize a dotted key so `a . "b"` and `a.b` compare equal."""
    parts = []
    for part in re.findall(TOML_KEY_PART, raw):
        if part.startswith('"'):
            try:
                part = json.loads(part)
            except ValueError:
                part = part[1:-1]
        elif part.startswith("'"):
            part = part[1:-1]
        parts.append(part)
    return ".".join(parts)


def toml_table_name(line: str) -> str | None:
    """Return the name of a `[table]` header line; array tables do not count."""
    match = TOML_TABLE_HEADER.match(line)
    if match is None or line.lstrip().startswith("[["):
        return None
    return toml_key_name(match.group(1))


def toml_statement_starts(lines: list[str]) -> list[int]:
    """Indexes of lines that begin a statement; lines inside multiline values are skipped."""
    starts: list[int] = []
    idx = 0
    while idx < len(lines):
        starts.append(idx)
        match = TOML_ASSIGNMENT_START.match(lines[idx])
        idx = toml_value_end_idx(lines, idx, match.group(1), match.group(2)) if match else idx + 1
    return starts


def find_first_toml_section_idx(lines: list[str]) -> int | None:
    return next((idx for idx in toml_statement_starts(lines)
                 if TOML_TABLE_HEADER.match(lines[idx])), None)


def ensure_top_level_config_line(lines: list[str], desired_line: str, key: str) -> list[str]:
    first_section_idx = find_first_toml_section_idx(lines)
    top_level_ranges = [
        (start, end) for start, end in find_toml_key_assignment_ranges(lines, key)
        if first_section_idx is None or start < first_section_idx
    ]

    if top_level_ranges:
        # Drop whole assignments, so a multiline value leaves no continuation lines behind.
        matching_set = {idx for start, end in top_level_ranges for idx in range(start, end)}
        new_lines: list[str] = []
        wrote_line = False
        for idx, line in enumerate(lines):
            if idx in matching_set:
                if not wrote_line:
                    new_lines.append(desired_line)
                    wrote_line = True
                continue
            new_lines.append(line)
        return new_lines

    insert_idx = first_section_idx if first_section_idx is not None else len(lines)
    return [*lines[:insert_idx], desired_line, *lines[insert_idx:]]


TOML_STRING_ASSIGNMENT = re.compile(
    rf"""^\s*({TOML_DOTTED_KEY})\s*=\s*(?:"((?:[^"\\]|\\.)*)"|'([^']*)')\s*(?:#.*)?$"""
)


def is_escaped(value: str, idx: int) -> bool:
    backslashes = 0
    while idx - backslashes > 0 and value[idx - backslashes - 1] == "\\":
        backslashes += 1
    return backslashes % 2 == 1


def toml_value_is_complete(value: str) -> bool:
    """Return whether brackets and strings in a TOML value are balanced."""
    depth = 0
    seen_value = False
    idx = 0
    while idx < len(value):
        char = value[idx]
        if char == "#":
            newline = value.find("\n", idx)
            if newline == -1:
                break
            idx = newline + 1
            continue
        if char in "\"'":
            quote = char * 3 if value.startswith(char * 3, idx) else char
            end = value.find(quote, idx + len(quote))
            # Only basic strings support escapes; skip quotes after an odd backslash run.
            while char == '"' and end != -1 and is_escaped(value, end):
                end = value.find(quote, end + 1)
            if end == -1:
                return False
            if len(quote) == 3:
                # Up to two content quotes may sit right before the closing delimiter, so
                # `"""a""""` closes at its last three quotes.
                extra = 0
                while extra < 2 and value.startswith(char, end + 3 + extra):
                    extra += 1
                end += extra
            seen_value = True
            idx = end + len(quote)
            continue
        if char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
        if not char.isspace():
            seen_value = True
        idx += 1
    return seen_value and depth <= 0


def toml_assignment_is_complete(key: str, value: str) -> bool:
    if tomllib is not None:
        try:
            _ = tomllib.loads(f"{key} = {value}\n")
        except tomllib.TOMLDecodeError:
            pass
        else:
            return True
    # Balanced brackets and quotes also end a value tomllib rejects (a typo, or a
    # TOML 1.1 multiline inline table), instead of swallowing the rest of the file.
    return toml_value_is_complete(value)


def read_toml_string_assignment(text: str, key: str) -> str | None:
    """Return the string value of a `key = "..."` assignment; the fallback reads one line."""
    if tomllib is not None:
        try:
            value = tomllib.loads(text).get(key)
        except tomllib.TOMLDecodeError:
            return None
        return value if isinstance(value, str) else None
    match = TOML_STRING_ASSIGNMENT.match(text)
    if match is None or toml_key_name(match.group(1)) != key:
        return None
    if match.group(3) is not None:
        return match.group(3)
    try:
        return json.loads(f'"{match.group(2)}"')
    except ValueError:
        return None


def toml_value_end_idx(lines: list[str], start_idx: int, key: str, first_value: str) -> int:
    """Return the index after the last line of the value that starts on `start_idx`."""
    value_lines = [first_value]
    for end_idx in range(start_idx + 1, len(lines) + 1):
        if toml_assignment_is_complete(key, "\n".join(value_lines)):
            return end_idx
        if end_idx == len(lines):
            return end_idx
        value_lines.append(lines[end_idx])
    return len(lines)


def find_toml_key_assignment_end_idx(lines: list[str], start_idx: int, key: str) -> int:
    match = TOML_ASSIGNMENT_START.match(lines[start_idx])
    if match is None or toml_key_name(match.group(1)) != key:
        return start_idx + 1
    return toml_value_end_idx(lines, start_idx, match.group(1), match.group(2))


def find_toml_key_assignment_ranges(lines: list[str], key: str) -> list[tuple[int, int]]:
    starts = toml_statement_starts(lines)
    ranges: list[tuple[int, int]] = []
    for pos, start in enumerate(starts):
        match = TOML_ASSIGNMENT_START.match(lines[start])
        if match and toml_key_name(match.group(1)) == key:
            ranges.append((start, starts[pos + 1] if pos + 1 < len(starts) else len(lines)))
    return ranges


def replace_toml_section(lines: list[str], section_name: str, section_lines: list[str]) -> list[str]:
    headers = [idx for idx in toml_statement_starts(lines) if TOML_TABLE_HEADER.match(lines[idx])]
    section_start = next((idx for idx in headers if toml_table_name(lines[idx]) == section_name), None)

    if section_start is None:
        if lines and lines[-1].strip():
            return [*lines, "", *section_lines]
        return [*lines, *section_lines]

    section_end = next((idx for idx in headers if idx > section_start), len(lines))
    return [*lines[:section_start], *section_lines, *lines[section_end:]]


def toml_basic_string(value: str) -> str:
    """Quote a TOML basic string; JSON escapes are valid TOML, unlike raw Windows backslashes."""
    # ensure_ascii=False: TOML rejects the surrogate pairs JSON uses for non-BMP characters.
    return json.dumps(value, ensure_ascii=False)


def parses(lines: list[str]) -> bool | None:
    """Whether the lines are valid TOML; None when tomllib is not available to tell."""
    if tomllib is None:
        return None
    try:
        _ = tomllib.loads("\n".join(lines))
    except tomllib.TOMLDecodeError:
        return False
    return True


def loads(lines: list[str]) -> dict | None:
    """The parsed document, or None when it is not valid TOML or tomllib is missing."""
    if tomllib is None:
        return None
    try:
        return tomllib.loads("\n".join(lines))
    except tomllib.TOMLDecodeError:
        return None
