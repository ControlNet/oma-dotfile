"""Merge a managed YAML file into the one on disk, line by line.

The standard library has no YAML parser, so only a simple shape is handled: top-level keys,
each either a one-line scalar or an indented block. A block that is a flat `key: value`
mapping in both files is merged key by key; any other block (lists, nested mappings) is taken
whole from the managed file. Keys only the file on disk has are kept, in their place; new
managed keys go last. Anything outside this shape (flow style, block scalars, anchors,
documents markers, tabs) is not merged: `blocks` and `merge` return None.
"""

import re

KEY = r"""(?:[A-Za-z0-9_.-]+|"[^"\\]*"|'[^']*')"""
TOP_KEY = re.compile(rf"^({KEY}):(?:[ ]+(.*))?$")
SUB_KEY = re.compile(rf"^([ ]+)({KEY}):[ ]+(\S.*)$")
# Values that start a multi-line or reference construct this module does not follow.
UNSUPPORTED_VALUE = re.compile(r"^[|>&*!]")

Block = tuple[str, list[str]]  # (top-level key, its lines with the `key:` line first)
Mapping = tuple[str, list[tuple[str, str]], list[str]]  # (indent, [(key, value)], trailing blanks)


def is_blank_or_comment(line: str) -> bool:
    return not line.strip() or line.lstrip().startswith("#")


def blocks(text: str) -> list[Block] | None:
    """Split text into top-level blocks, or None if it is not in the supported shape."""
    result: list[Block] = []
    for line in text.splitlines():
        if "\t" in line:
            return None
        if line[:1] in ("", " ", "#"):
            if not result:
                if line.strip():  # an indented line or comment before the first key
                    return None
                continue
            result[-1][1].append(line)
            continue
        match = TOP_KEY.match(line)
        if match is None or any(key == match.group(1) for key, _ in result):
            return None
        value = (match.group(2) or "").strip()
        if value and UNSUPPORTED_VALUE.match(value):
            return None
        result.append((match.group(1), [line]))
    for _, lines in result:
        header_value = TOP_KEY.match(lines[0]).group(2)
        if header_value and header_value.strip() and not all(is_blank_or_comment(line) for line in lines[1:]):
            return None  # `key: value` followed by indented lines
    return result


def flat_mapping(lines: list[str]) -> Mapping | None:
    """The block as a flat `key: value` mapping, or None if it is anything else."""
    header_value = TOP_KEY.match(lines[0]).group(2)
    if header_value and header_value.strip():
        return None
    body = lines[1:]
    trailing: list[str] = []
    while body and not body[-1].strip():
        trailing.insert(0, body.pop())
    entries = []
    indents = set()
    for line in body:
        match = SUB_KEY.match(line)
        if match is None or UNSUPPORTED_VALUE.match(match.group(3)):
            return None
        indents.add(match.group(1))
        entries.append((match.group(2), match.group(3)))
    if not entries or len(indents) != 1:
        return None
    return indents.pop(), entries, trailing


def merge_block(existing: list[str], managed: list[str]) -> list[str]:
    old = flat_mapping(existing)
    new = flat_mapping(managed)
    if old is None or new is None:
        return managed
    indent, old_entries, trailing = old
    new_values = dict(new[1])
    merged = [(key, new_values.get(key, value)) for key, value in old_entries]
    known = {key for key, _ in old_entries}
    merged += [(key, value) for key, value in new[1] if key not in known]
    return [existing[0], *(f"{indent}{key}: {value}" for key, value in merged), *trailing]


def merge(existing: str, managed: str) -> str | None:
    """existing with every managed key set; None if either is not in the supported shape.

    When nothing changes, existing is returned as it is (even without a final newline).
    """
    old = blocks(existing)
    new = blocks(managed)
    if old is None or new is None:
        return None
    new_blocks = dict(new)
    old_keys = {key for key, _ in old}
    merged = [merge_block(lines, new_blocks[key]) if key in new_blocks else lines for key, lines in old]
    merged += [lines for key, lines in new if key not in old_keys]
    text = "".join(line + "\n" for lines in merged for line in lines)
    if text.rstrip("\n") == existing.rstrip("\n"):
        return existing
    return text
