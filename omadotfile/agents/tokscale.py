"""Tokscale: merge this repo's model aliases into its settings.json."""

from collections.abc import Mapping
from functools import partial
import json
from pathlib import Path
import sys

from omadotfile.agents.base import Agent, agent
from omadotfile.console import info, success
from omadotfile.constants import TOKSCALE_MODEL_ALIASES
from omadotfile.context import Context
from omadotfile.core.codec import JSON, JsonObject
from omadotfile.core.errors import warns_on


def parse_aliases(text: str) -> dict[str, str]:
    """The repo's alias table; ValueError unless it maps non-empty strings to non-empty strings."""
    aliases = json.loads(text)
    if not isinstance(aliases, dict) or not all(
        isinstance(key, str) and key.strip() and isinstance(value, str) and value.strip()
        for key, value in aliases.items()
    ):
        raise ValueError("Model aliases must be a non-empty-string mapping")
    return aliases


def with_aliases(aliases: dict[str, str], settings: JsonObject) -> JsonObject:
    """Settings with the managed aliases merged over the user's own."""
    existing = settings.get("modelAliases", {})
    if not isinstance(existing, dict):
        raise ValueError("Existing modelAliases must be a JSON object")
    merged = {**existing, **aliases}
    if existing == merged and "modelAliases" in settings:
        return settings
    return {**settings, "modelAliases": merged}


@warns_on(OSError, ValueError,
          message="Failed to load Tokscale aliases/settings ({error}); leaving settings unchanged")
def install_model_aliases(ctx: Context, config_dir: Path) -> None:
    """Merge managed aliases while preserving unrelated user settings."""
    aliases = parse_aliases((ctx.repo / TOKSCALE_MODEL_ALIASES).read_text(encoding="utf-8"))
    dst = config_dir / "settings.json"
    existed = dst.exists()
    if not ctx.files.update(dst, JSON, partial(with_aliases, aliases), default={}):
        info("Tokscale model aliases already configured; skip")
        return
    if existed:
        info(f"Updated {dst}; preserved unrelated settings (backup enabled: {ctx.options.backup})")
    success(f"Configured Tokscale model aliases: {dst}")


# Tokscale ships no CLI; it is detected from its configuration directory.
@agent("tokscale", label="Tokscale", executable=None)
class Tokscale(Agent):
    creates_dir = False  # only once there are aliases to write

    @staticmethod
    def config_dir(env: Mapping[str, str], home: Path) -> Path:
        """Follow Tokscale's platform defaults and native directory override."""
        override = env.get("TOKSCALE_CONFIG_DIR", "")
        if override:
            return Path(override)
        if sys.platform == "win32" and env.get("APPDATA"):
            return Path(env["APPDATA"]) / "tokscale"
        if sys.platform != "darwin" and env.get("XDG_CONFIG_HOME"):
            return Path(env["XDG_CONFIG_HOME"]) / "tokscale"
        return home / ".config" / "tokscale"

    def detect(self, env: Mapping[str, str], home: Path) -> bool:
        return self.config_dir(env, home).is_dir()

    def title(self, ctx: Context) -> str:
        return "Configuring Tokscale model aliases"

    def skip_reason(self, ctx: Context) -> str:
        return "tokscale config directory not found"

    @staticmethod
    def configure(ctx: Context, target: Path) -> None:
        install_model_aliases(ctx, target)
