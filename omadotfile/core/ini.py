"""Set keys in one section of an INI file, keeping every other line as it is."""

import re


def set_section_keys(content: str, section: str, values: dict[str, str],
                     aliases: dict[str, tuple[str, ...]]) -> str:
    """Set each key of values in [section]; every spelling in aliases[key] is replaced."""
    lines = content.splitlines()
    header = f"[{section}]".lower()
    start = next((idx for idx, line in enumerate(lines)
                  if line.strip().lower() == header), None)
    if start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"[{section}]")
        start = len(lines) - 1
    end = next((idx for idx in range(start + 1, len(lines))
                if lines[idx].strip().startswith("[")), len(lines))
    body = lines[start + 1:end]

    for key, value in values.items():
        spellings = "|".join(re.escape(alias) for alias in aliases.get(key, (key,)))
        pattern = re.compile(rf"^\s*(?:{spellings})\s*[=:]")
        matches = [idx for idx, line in enumerate(body) if pattern.match(line)]
        desired = f"{key} = {value}"
        if matches:
            body[matches[0]] = desired
            body = [line for idx, line in enumerate(body) if idx not in matches[1:]]
        else:
            # Insert after the last setting, before the blank lines that end the section.
            insert_idx = len(body)
            while insert_idx > 0 and not body[insert_idx - 1].strip():
                insert_idx -= 1
            body.insert(insert_idx, desired)

    return "\n".join([*lines[:start + 1], *body, *lines[end:]]) + "\n"
