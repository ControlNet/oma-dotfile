"""Codex: AGENTS.md, the Gotify notifier, and config.toml (notify, provider, skills)."""

from collections.abc import Mapping
import json
from pathlib import Path
import re
import sys

from omadotfile.agents.base import Agent
from omadotfile.console import info, success, warn
from omadotfile.constants import CODEX_DISABLED_SHARED_SKILLS, CODEX_FILES
from omadotfile.context import Context
from omadotfile.core import toml_edit
from omadotfile.core.toml_edit import (TOML_ASSIGNMENT_START, TOML_TABLE_HEADER,
                                       ensure_top_level_config_line, find_first_toml_section_idx,
                                       find_toml_key_assignment_ranges, read_toml_string_assignment,
                                       replace_toml_section, toml_basic_string, toml_key_name,
                                       toml_statement_starts)


def ensure_oauth_provider(lines: list[str]) -> list[str]:
    """Comment the managed top-level gateway selector; preserve other settings."""
    end = find_first_toml_section_idx(lines)
    top_level = lines if end is None else lines[:end]
    result: list[str] = []
    idx = 0
    for start, stop in find_toml_key_assignment_ranges(top_level, "model_provider"):
        result.extend(lines[idx:start])
        assignment = lines[start:stop]
        if read_toml_string_assignment("\n".join(assignment), "model_provider") != "codex_api":
            result.extend(assignment)
        elif len(assignment) == 1:
            result.append("# " + assignment[0])
        else:
            # Collapse a multiline value into one commented line that API mode can restore.
            result.append('# model_provider = "codex_api"')
        idx = stop
    result.extend(lines[idx:])
    return result


def ensure_api_provider(lines: list[str], codex_base_url: str) -> list[str]:
    """Select the gateway as the model provider; CODEX_BASE_URL is its base_url."""
    if not codex_base_url:
        warn("CODEX_BASE_URL is not set; skip Codex model provider config in config.toml.")
        return lines

    # Reuse a commented gateway selector so repeated switches do not add lines.
    first_section = find_first_toml_section_idx(lines)
    end = len(lines) if first_section is None else first_section
    lines = list(lines)
    for idx in toml_statement_starts(lines[:end]):
        match = re.match(r"^\s*#\s*(.*)$", lines[idx])
        assignment = TOML_ASSIGNMENT_START.match(match.group(1)) if match else None
        if assignment and toml_key_name(assignment.group(1)) == "model_provider":
            if read_toml_string_assignment(match.group(1), "model_provider") == "codex_api":
                lines[idx] = match.group(1)
    lines = ensure_top_level_config_line(
        lines, 'model_provider = "codex_api"', "model_provider"
    )
    return replace_toml_section(
        lines,
        "model_providers.codex_api",
        [
            "[model_providers.codex_api]",
            'name = "codex_api"',
            f"base_url = {json.dumps(codex_base_url)}",
            'env_key = "CODEX_API_TOKEN"',
            'wire_api = "responses"',
        ],
    )


def ensure_notify(lines: list[str], codex_dir: Path) -> list[str]:
    """Point Codex's top-level `notify` at the Gotify notifier, run by this Python."""
    python_bin = sys.executable or "python3"
    script_path = codex_dir / "codex-gotify-notify.py"
    desired_line = f"notify = [{toml_basic_string(python_bin)}, {toml_basic_string(str(script_path))}]"
    first_section_idx = find_first_toml_section_idx(lines)
    notify_ranges = find_toml_key_assignment_ranges(lines, "notify")

    if notify_ranges:
        new_lines: list[str] = []
        wrote_top_notify = False
        idx = 0
        for start_idx, end_idx in notify_ranges:
            new_lines.extend(lines[idx:start_idx])
            is_top_level = first_section_idx is None or start_idx < first_section_idx
            if is_top_level and not wrote_top_notify:
                new_lines.append(desired_line)
                wrote_top_notify = True
            idx = end_idx
        new_lines.extend(lines[idx:])

        if not wrote_top_notify:
            insert_idx = find_first_toml_section_idx(new_lines)
            if insert_idx is None:
                insert_idx = len(new_lines)
            new_lines.insert(insert_idx, desired_line)
        return new_lines

    insert_idx = first_section_idx if first_section_idx is not None else len(lines)
    return [*lines[:insert_idx], desired_line, *lines[insert_idx:]]


def skills_config_is_static(lines: list[str]) -> bool:
    """Whether skills.config is defined in a way `[[skills.config]]` cannot extend.

    An inline array (`config = [...]` under `[skills]`, `skills.config = [...]`,
    `skills = { config = ... }`) or a plain `[skills.config]` table makes an appended
    array-of-tables entry invalid TOML.
    """
    table: str | None = ""
    seen_entry = False
    for idx in toml_statement_starts(lines):
        line = lines[idx]
        header = TOML_TABLE_HEADER.match(line)
        if header:
            name = toml_key_name(header.group(1))
            if line.lstrip().startswith("[["):
                table = None  # keys below belong to an array element
                seen_entry = seen_entry or name == "skills.config"
            elif name == "skills.config" or (name.startswith("skills.config.") and not seen_entry):
                # [skills.config.x] before any entry makes skills.config a plain table.
                return True
            else:
                table = name
            continue
        assignment = TOML_ASSIGNMENT_START.match(line)
        if assignment and table is not None:
            key = toml_key_name(assignment.group(1))
            full = f"{table}.{key}" if table else key
            # Under [skills.config.x] after [[skills.config]], keys belong to an element.
            if full in ("skills", "skills.config") or (
                    table in ("", "skills") and full.startswith("skills.config.")):
                return True
    return False


def skill_path_already_disabled(lines: list[str], skill_path: str) -> bool:
    """Whether a path-only skills.config entry already disables skill_path (needs tomllib)."""
    document = toml_edit.loads(lines)
    if document is None:
        return False
    skills = document.get("skills")
    entries = skills.get("config") if isinstance(skills, dict) else None
    return isinstance(entries, list) and any(
        isinstance(entry, dict) and entry.get("path") == skill_path
        and "name" not in entry and entry.get("enabled") is False
        for entry in entries)


def ensure_skill_path_disabled(lines: list[str], skill_path: str) -> list[str]:
    """Make a `[[skills.config]]` entry for skill_path say `enabled = false`.

    Codex ignores an entry that names both a path and a name, so such entries are not
    reused. A skills.config written inline is left for the user to edit.
    """
    if skill_path_already_disabled(lines, skill_path):
        return lines
    if skills_config_is_static(lines):
        warn(f"skills.config in Codex config.toml is not written as [[skills.config]] entries; "
             f"add one with path = {toml_basic_string(skill_path)} and enabled = false by hand")
        return lines
    headers = [idx for idx in toml_statement_starts(lines) if TOML_TABLE_HEADER.match(lines[idx])]
    for pos, start in enumerate(headers):
        header = TOML_TABLE_HEADER.match(lines[start])
        if not lines[start].lstrip().startswith("[[") or toml_key_name(header.group(1)) != "skills.config":
            continue
        end = headers[pos + 1] if pos + 1 < len(headers) else len(lines)
        block = lines[start + 1:end]
        paths = find_toml_key_assignment_ranges(block, "path")
        if find_toml_key_assignment_ranges(block, "name") or not any(
                read_toml_string_assignment("\n".join(block[a:b]), "path") == skill_path
                for a, b in paths):
            continue
        enabled = find_toml_key_assignment_ranges(block, "enabled")
        a, b = enabled[0] if enabled else (paths[0][1], paths[0][1])
        block = [*block[:a], "enabled = false", *block[b:]]
        return keep_valid_toml(lines, [*lines[:start + 1], *block, *lines[end:]], skill_path)
    entry = ["[[skills.config]]", f"path = {toml_basic_string(skill_path)}", "enabled = false"]
    return keep_valid_toml(
        lines, [*lines, "", *entry] if lines and lines[-1].strip() else [*lines, *entry], skill_path)


def keep_valid_toml(lines: list[str], new_lines: list[str], skill_path: str) -> list[str]:
    """Return new_lines unless they break a config.toml that parsed before."""
    if toml_edit.parses(lines) is not True:
        return new_lines
    if not toml_edit.parses(new_lines):
        warn(f"Could not add a skills.config entry for {skill_path} to Codex config.toml "
             f"without breaking it; add one with enabled = false by hand")
        return lines
    return new_lines


def ensure_shared_skills_disabled(lines: list[str], skills_dir: Path) -> list[str]:
    """Disable, in Codex only, the shared copies of skills Codex already bundles.

    The selector is the path: a name selector would hide Codex's bundled copy as well.
    """
    for name in CODEX_DISABLED_SHARED_SKILLS:
        lines = ensure_skill_path_disabled(lines, str(skills_dir / name / "SKILL.md"))
    return lines


def ensure_config(ctx: Context, codex_dir: Path) -> None:
    config_path = codex_dir / "config.toml"
    if config_path.exists():
        try:
            content = config_path.read_text(encoding="utf-8")
        except OSError as exc:
            warn(f"Failed to read {config_path}: {exc}")
            return
        lines = content.splitlines()
    else:
        lines = []

    new_lines = ensure_notify(lines, codex_dir)
    new_lines = ensure_shared_skills_disabled(new_lines, ctx.shared_skills_dir)
    new_lines = (ensure_oauth_provider(new_lines) if ctx.options.oauth
                 else ensure_api_provider(new_lines, ctx.env.get("CODEX_BASE_URL", "").strip()))

    if new_lines == lines:
        info("Codex config already configured; skip")
        return

    ctx.files.write_text(config_path, "\n".join(new_lines) + "\n")
    success(f"Configured Codex config: {config_path}")


class Codex(Agent):
    key = "codex"
    files = CODEX_FILES

    @classmethod
    def config_dir(cls, env: Mapping[str, str], home: Path) -> Path:
        if env.get("CODEX_DIR", ""):
            return Path(env["CODEX_DIR"])
        codex_home = env.get("CODEX_HOME", "").strip()
        if codex_home:
            return Path(codex_home)
        return home / ".codex"

    def title(self, ctx: Context) -> str:
        return f"Installing Codex assets and config to: {self.target_dir(ctx)}"

    def configure(self, ctx: Context, target: Path) -> None:
        ensure_config(ctx, target)
