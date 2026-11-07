"""Tokscale: merge this repo's model aliases into its settings.json."""

from collections.abc import Mapping
import json
from pathlib import Path
import sys

from omadotfile.agents.base import Agent
from omadotfile.console import info, success, warn
from omadotfile.constants import TOKSCALE_MODEL_ALIASES
from omadotfile.context import Context


def install_model_aliases(ctx: Context, config_dir: Path) -> None:
    """Merge managed aliases while preserving unrelated user settings."""
    src = ctx.repo / TOKSCALE_MODEL_ALIASES
    dst = config_dir / "settings.json"
    try:
        aliases = json.loads(src.read_text(encoding="utf-8"))
        if not isinstance(aliases, dict) or not all(
            isinstance(key, str) and key.strip()
            and isinstance(value, str) and value.strip()
            for key, value in aliases.items()
        ):
            raise ValueError("Model aliases must be a non-empty-string mapping")
        settings = json.loads(dst.read_text(encoding="utf-8")) if dst.exists() else {}
        if not isinstance(settings, dict):
            raise ValueError("Tokscale settings must be a JSON object")
        existing = settings.get("modelAliases", {})
        if not isinstance(existing, dict):
            raise ValueError("Existing modelAliases must be a JSON object")
        merged = {**existing, **aliases}
        if existing == merged and "modelAliases" in settings:
            info("Tokscale model aliases already configured; skip")
            return
        settings["modelAliases"] = merged
        content = json.dumps(settings, indent=2, ensure_ascii=False) + "\n"
    except (OSError, ValueError) as exc:
        warn(f"Failed to load Tokscale aliases/settings ({type(exc).__name__}); leaving settings unchanged")
        return

    if dst.exists():
        info(f"Updating {dst}; preserving unrelated settings (backup enabled: {ctx.options.backup})")
    ctx.files.write_text(dst, content)
    success(f"Configured Tokscale model aliases: {dst}")


class Tokscale(Agent):
    key = "tokscale"
    creates_dir = False  # only once there are aliases to write

    @classmethod
    def config_dir(cls, env: Mapping[str, str], home: Path) -> Path:
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

    def configure(self, ctx: Context, target: Path) -> None:
        install_model_aliases(ctx, target)
