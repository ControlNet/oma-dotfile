"""OpenCode: config files, the OAuth variant of opencode.jsonc, plugins, old config names."""

from collections.abc import Mapping
import json
from pathlib import Path
import sys

from omadotfile.agents.base import Agent, agent
from omadotfile.console import item
from omadotfile.constants import (LEGACY_OPENAGENT_CONFIG_NAMES, LEGACY_OPENCODE_JSON,
                                  OPENCODE_FILES, OPENCODE_PLUGINS_DIR)
from omadotfile.context import Context
from omadotfile.core.jsonc import merge_config_objects, read_jsonc_object
from omadotfile.migration import migration


def render_oauth_config(src: Path, config_dir: Path, dst: Path) -> str:
    """opencode.jsonc without the gateway `codex` provider, keeping one the user configured.

    OpenCode loads opencode.json before opencode.jsonc and JSONC wins on conflicts, so a
    `codex` provider found in either is merged in that order.
    """
    document = read_jsonc_object(src)
    providers = document.setdefault("provider", {})
    providers.pop("codex", None)
    existing_codex = {}
    has_codex = False
    for existing_path in (config_dir / LEGACY_OPENCODE_JSON, dst):
        if existing_path.exists():
            existing = read_jsonc_object(existing_path).get("provider", {})
            if not isinstance(existing, dict):
                raise ValueError(f"Expected provider object in {existing_path}")
            if "codex" in existing:
                if not isinstance(existing["codex"], dict):
                    raise ValueError(f"Expected codex provider object in {existing_path}")
                existing_codex = merge_config_objects(existing_codex, existing["codex"])
                has_codex = True
    if has_codex:
        providers["codex"] = existing_codex
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


@migration(since="2026-02", reason="opencode.json from before the switch to opencode.jsonc",
           remove_by="2027-02")
def retire_legacy_opencode_json(ctx: Context, config_dir: Path) -> None:
    ctx.files.retire(config_dir / LEGACY_OPENCODE_JSON)


@migration(since="2026-04", reason="oh-my-opencode / oh-my-openagent config names",
           remove_by="2027-04")
def retire_legacy_openagent_files(ctx: Context, config_dir: Path) -> None:
    for name in LEGACY_OPENAGENT_CONFIG_NAMES:
        ctx.files.retire(config_dir / name)


# The OMO OpenCode plugin has no executable of its own, so the OpenCode target gates its config.
@agent("opencode", label="OpenCode/OMO", executable="opencode")
class OpenCode(Agent):
    files = OPENCODE_FILES

    @staticmethod
    def config_dir(env: Mapping[str, str], home: Path) -> Path:
        if env.get("CONFIG_DIR", ""):
            return Path(env["CONFIG_DIR"])
        if sys.platform == "win32":
            return home / ".config" / "opencode"
        xdg_config = env.get("XDG_CONFIG_HOME", "")
        if xdg_config:
            return Path(xdg_config) / "opencode"
        return home / ".config" / "opencode"

    def title(self, ctx: Context) -> str:
        return f"Installing OpenCode config files and plugins to: {self.target_dir(ctx)}"

    @staticmethod
    def install_oauth_file(ctx: Context, src: Path, dst: Path) -> None:
        ctx.files.write_text(dst, render_oauth_config(src, dst.parent, dst))

    @staticmethod
    def configure(ctx: Context, target: Path) -> None:
        # After the files: render_oauth_config reads opencode.json before it is retired.
        retire_legacy_opencode_json(ctx, target)
        retire_legacy_openagent_files(ctx, target)
        plugins = ctx.repo / OPENCODE_PLUGINS_DIR
        if plugins.exists():
            item(f"{OPENCODE_PLUGINS_DIR}/ (replace managed items)")
            ctx.files.copy_items(plugins, target / OPENCODE_PLUGINS_DIR)
