"""~/.omo/omo.jsonc: OMO config shared by the OMO OpenCode plugin and OMO Native."""

from pathlib import Path

from omadotfile.agents.base import Component
from omadotfile.constants import LEGACY_OMO_CONFIG_NAMES, OMO_FILES
from omadotfile.context import Context
from omadotfile.core.jsonc import find_jsonc_top_level_object, rewrite_model_prefix
from omadotfile.migration import migration
from omadotfile.step import found_any


def omo_dir(home: Path) -> Path:
    """The OMO configuration directory."""
    return home / ".omo"


def render_oauth_config(content: str) -> str:
    """OpenCode reaches ChatGPT OAuth as `openai/`; OMO Native calls it `chatgpt-subscription/`."""
    native = find_jsonc_top_level_object(content, "[native]")
    if native is None:
        return rewrite_model_prefix(content, "openai")
    start, end = native
    return (rewrite_model_prefix(content[:start], "openai")
            + rewrite_model_prefix(content[start:end], "chatgpt-subscription")
            + rewrite_model_prefix(content[end:], "openai"))


@migration(since="2026-08", reason="config.json(c) in ~/.omo before omo.jsonc", remove_by="2027-08")
def retire_legacy_omo_files(ctx: Context, directory: Path) -> None:
    for name in LEGACY_OMO_CONFIG_NAMES:
        ctx.files.retire(directory / name)


class OmoConfig(Component):
    files = OMO_FILES

    def title(self, ctx: Context) -> str:
        return f"Installing unified OMO config to: {self.target_dir(ctx)}"

    def enabled(self, ctx: Context) -> bool:
        return found_any("opencode", "omo")(ctx)

    def skip_reason(self, ctx: Context) -> str:
        return "neither opencode nor omo found"

    def target_dir(self, ctx: Context) -> Path:
        return omo_dir(ctx.home)

    @staticmethod
    def install_oauth_file(ctx: Context, src: Path, dst: Path) -> None:
        ctx.files.write_text(dst, render_oauth_config(src.read_text(encoding="utf-8")))

    @staticmethod
    def configure(ctx: Context, target: Path) -> None:
        retire_legacy_omo_files(ctx, target)
