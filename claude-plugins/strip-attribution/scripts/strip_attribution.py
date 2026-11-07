"""Claude Code PreToolUse hook: drop Claude attribution from commit and PR commands.

The command is rewritten through `updatedInput`, never blocked, so Claude does not retry
it, and the user's permission rules still decide whether the rewritten command runs. Only
commands that run `git commit` or `gh pr create|edit` are touched. Message files they read
(`-F`, `--file`, `--body-file`) are cleaned in place, since their text is not in the command.
"""

import json
import os
from pathlib import Path
import re
import sys

# Matched case-insensitively and never past a quote, so a closing quote stays. Claude Code
# asks for the session link with a `Claude-Session:` key in commits and bare in PRs.
ATTRIBUTION = (
    r"(?:Co-Authored-By:[ \t]*Claude\b[^\n<\"']*<[^>\n]*anthropic\.com>"
    r"|(?:🤖[ \t]*)?Generated with \[Claude Code\](?:\([^\s)\"']*\))?"
    r"|(?:Claude-Session:[ \t]*)?https://claude\.ai/code/session_[^\s\"')]*)"
)
# A whole line of attribution, or one followed by what closes the message (`"`, `'`, `)`)
# and the rest of the command, which are kept.
LINE_RE = re.compile(rf"[ \t]*{ATTRIBUTION}[ \t]*(?P<tail>[\"')].*)?", re.IGNORECASE)
# A message or trailer argument that holds nothing but attribution.
ARG_RE = re.compile(
    rf"[ \t]+(?:-m|--message|--trailer)(?:[ \t]+|=)(?P<q>[\"']){ATTRIBUTION}(?P=q)", re.IGNORECASE
)
COMMIT_RE = re.compile(
    r"\bgit(?:[ \t]+-\S+(?:[ \t]+[^\s-]\S*)?)*?[ \t]+commit(?![\w-])|\bgh[ \t]+pr[ \t]+(?:create|edit)\b"
)
FILE_RE = re.compile(
    r"(?:^|[ \t])(?:-F|--file|--body-file)(?:[ \t]+|=)(\"[^\"\n]*\"|'[^'\n]*'|[^\s;&|<>()]+)"
)
SEGMENT_RE = re.compile(r"&&|\|\||[;|\n]")


def strip_lines(text: str) -> str:
    kept: list[str] = []
    for line in text.split("\n"):
        match = LINE_RE.fullmatch(line)
        if match is None:
            kept.append(line)
        elif match["tail"]:
            kept.append(match["tail"])
    return "\n".join(kept)


def strip_command(command: str) -> str | None:
    """The command without attribution, or None when it is not a commit or has none."""
    if not COMMIT_RE.search(command):
        return None
    stripped = strip_lines(ARG_RE.sub("", command))
    return stripped if stripped != command else None


def clean_message_files(command: str, cwd: str) -> None:
    for segment in SEGMENT_RE.split(command):
        if not COMMIT_RE.search(segment):
            continue
        for match in FILE_RE.finditer(segment):
            name = match.group(1)
            if name[0] in "\"'":
                name = name[1:-1]
            if not name or name == "-":
                continue
            path = Path(cwd) / os.path.expanduser(name)
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            stripped = strip_lines(text)
            if stripped != text:
                _ = path.write_text(stripped, encoding="utf-8")


def main() -> None:
    payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    tool_input = payload.get("tool_input") if isinstance(payload, dict) else None
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        return
    try:
        clean_message_files(command, payload.get("cwd") or os.getcwd())
    except (OSError, UnicodeError, ValueError):
        pass
    stripped = strip_command(command)
    if stripped is None:
        return
    # No permissionDecision: the rewritten command goes through the usual permission checks.
    output = {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                     "updatedInput": {**tool_input, "command": stripped}}}
    _ = sys.stdout.write(json.dumps(output))


if __name__ == "__main__":
    try:
        main()
    except Exception:  # The command must run even if this hook breaks.
        pass
    sys.exit(0)
