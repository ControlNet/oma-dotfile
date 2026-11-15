"""Merge a managed YAML file into the one on disk, line by line.

The standard library has no YAML parser, so only a simple shape is handled: top-level keys,
each either a one-line scalar or an indented block. A block that is a flat `key: value`
mapping in both files (comments and blank lines allowed) is merged key by key, in place; any
other block (lists, nested mappings) is taken whole from the managed file. Keys only the file
on disk has are kept, in their place; new managed keys go last. Comments before the first key
are kept. Anything outside this shape (flow style, block scalars, anchors, document markers,
tabs) raises ValueError naming what was not understood.
"""

from dataclasses import dataclass
import re

KEY = r"""(?:[A-Za-z0-9_.-]+|"[^"\\]*"|'[^']*')"""
TOP_KEY = re.compile(rf"^({KEY}):(?:[ ]+(.*))?$")
SUB_KEY = re.compile(rf"^([ ]+)({KEY}):[ ]+(\S.*)$")
# Values that start a multi-line or reference construct this module does not follow.
UNSUPPORTED_VALUE = re.compile(r"^[|>&*!]")


@dataclass(frozen=True)
class Block:
    key: str
    value: str  # what follows `key:` on its own line; empty for an indented block
    lines: tuple[str, ...]  # all of the block's lines, the `key:` line first


@dataclass(frozen=True)
class FlatMapping:
    indent: str
    entries: tuple[tuple[str, str], ...]  # (key, value) in file order
    body: tuple[str, ...]  # the lines after `key:`, comments and blank lines included
    trailing: tuple[str, ...]  # blank lines that end the block


def is_blank_or_comment(line: str) -> bool:
    return not line.strip() or line.lstrip().startswith("#")


def parse_header(line: str, number: int) -> tuple[str, str]:
    match = TOP_KEY.match(line)
    if match is None:
        raise ValueError(f"line {number} is not a top-level `key:`")
    value = (match.group(2) or "").strip()
    if value and UNSUPPORTED_VALUE.match(value):
        raise ValueError(f"line {number} starts a block scalar, anchor or tag")
    return match.group(1), value


def blocks(text: str) -> list[Block]:
    """Split text into top-level blocks; ValueError if it is not in the supported shape."""
    found: list[tuple[str, str, list[str]]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if "\t" in line:
            raise ValueError(f"line {number} has a tab")
        if line[:1] in ("", " ", "#"):
            if found:
                found[-1][2].append(line)
            elif not is_blank_or_comment(line):
                raise ValueError(f"line {number} comes before the first key")
            continue
        key, value = parse_header(line, number)
        if any(key == other for other, _, _ in found):
            raise ValueError(f"key {key} appears twice")
        found.append((key, value, [line]))
    for key, value, lines in found:
        if value and not all(is_blank_or_comment(line) for line in lines[1:]):
            raise ValueError(f"key {key} has a value and indented lines")
    return [Block(key, value, tuple(lines)) for key, value, lines in found]


def flat_mapping(block: Block) -> FlatMapping | None:
    """The block as a flat `key: value` mapping, or None if it is anything else."""
    if block.value:
        return None
    body = list(block.lines[1:])
    trailing: list[str] = []
    while body and not body[-1].strip():
        trailing.insert(0, body.pop())
    entries: list[tuple[str, str]] = []
    indents: set[str] = set()
    for line in body:
        if is_blank_or_comment(line):
            continue
        match = SUB_KEY.match(line)
        if match is None or UNSUPPORTED_VALUE.match(match.group(3)):
            return None
        indents.add(match.group(1))
        entries.append((match.group(2), match.group(3)))
    if not entries or len(indents) != 1:
        return None
    return FlatMapping(indents.pop(), tuple(entries), tuple(body), tuple(trailing))


def merge_block(existing: Block, managed: Block) -> tuple[str, ...]:
    """The existing block's lines with managed values set in place; new keys after the last entry.

    Comments and blank lines stay where they are, so a comment no longer turns the user's
    mapping into one the managed block replaces whole.
    """
    old = flat_mapping(existing)
    new = flat_mapping(managed)
    if old is None or new is None:
        return managed.lines
    new_values = dict(new.entries)
    lines: list[str] = []
    after_last_entry = 0
    for line in old.body:
        match = SUB_KEY.match(line)
        if match is not None:
            key = match.group(2)
            if key in new_values:
                line = f"{match.group(1)}{key}: {new_values[key]}"
            lines.append(line)
            after_last_entry = len(lines)
        else:
            lines.append(line)
    known = {key for key, _ in old.entries}
    lines[after_last_entry:after_last_entry] = [f"{old.indent}{key}: {value}"
                                                for key, value in new.entries if key not in known]
    return (existing.lines[0], *lines, *old.trailing)


def preamble(text: str) -> list[str]:
    """The comment and blank lines before the first key."""
    lines: list[str] = []
    for line in text.splitlines():
        if not is_blank_or_comment(line):
            break
        lines.append(line)
    return lines


def merge(existing: str, managed: str) -> str:
    """existing with every managed key set; ValueError if either is not in the supported shape.

    When nothing changes, existing is returned as it is (even without a final newline).
    """
    old = blocks(existing)
    new = {block.key: block for block in blocks(managed)}
    old_keys = {block.key for block in old}
    merged = [merge_block(block, new[block.key]) if block.key in new else block.lines for block in old]
    merged += [block.lines for key, block in new.items() if key not in old_keys]
    merged.insert(0, tuple(preamble(existing)) if old else ())
    text = "".join(line + "\n" for lines in merged for line in lines)
    return existing if text.rstrip("\n") == existing.rstrip("\n") else text
