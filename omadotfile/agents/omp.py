"""oh-my-pi (OMP): config, AGENTS.md, Gotify and WakaTime extensions, models.yml."""

from collections.abc import Mapping
import json
from pathlib import Path
import re

from omadotfile.agents.base import Agent
from omadotfile.console import info, item, warn
from omadotfile.constants import FileSpec, OMP_FILES, OMP_MODELS, OMP_MODELS_DST, OMP_MODELS_OAUTH
from omadotfile.context import Context
from omadotfile.core import yaml_merge

BASE_URL_PLACEHOLDER = re.compile(r'^(\s*baseUrl:\s*)(["\']?)CODEX_BASE_URL\2(\s*(?:#.*)?)$', re.MULTILINE)


def render_oauth_config(content: str) -> str:
    """OMP reaches ChatGPT OAuth through its built-in `openai-codex` provider."""
    return content.replace("codex_api/", "openai-codex/")


def render_models(content: str, codex_base_url: str) -> tuple[str, bool]:
    """Render omp_models.yaml by inlining CODEX_BASE_URL placeholder."""
    quoted_url = json.dumps(codex_base_url)
    rendered, count = BASE_URL_PLACEHOLDER.subn(
        lambda m: f"{m.group(1)}{quoted_url}{m.group(3)}", content
    )
    return rendered, count > 0


def install_models(ctx: Context, agent_dir: Path) -> None:
    """Install native OAuth overrides or the configured gateway model catalog."""
    src = ctx.repo / OMP_MODELS
    if not src.exists():
        return
    dst = agent_dir / OMP_MODELS_DST
    if ctx.options.oauth:
        item(f"{OMP_MODELS_OAUTH} (native model overrides)")
        oauth_src = ctx.repo / OMP_MODELS_OAUTH
        try:
            content = oauth_src.read_text(encoding="utf-8")
        except OSError as exc:
            warn(f"Failed to read {oauth_src}: {exc}")
            return
        ctx.files.write_text(dst, content)
        return
    item(f"{OMP_MODELS} (render CODEX_BASE_URL)")
    try:
        content = src.read_text(encoding="utf-8")
    except OSError as exc:
        warn(f"Failed to read {src}: {exc}")
        return

    codex_base_url = ctx.env.get("CODEX_BASE_URL", "").strip()
    if codex_base_url:
        content, replaced = render_models(content, codex_base_url)
        if replaced:
            info("Injected CODEX_BASE_URL into omp models.yml")
        else:
            warn("No `baseUrl: CODEX_BASE_URL` placeholder found in omp_models.yaml")
    else:
        warn("CODEX_BASE_URL is not set; leaving `baseUrl: CODEX_BASE_URL` in omp models.yml. oh-my-pi will not auto-expand it.")

    try:
        ctx.files.write_text(dst, content)
    except OSError as exc:
        warn(f"Failed to write {dst}: {exc}")


class Omp(Agent):
    key = "omp"
    files = OMP_FILES

    @classmethod
    def config_dir(cls, env: Mapping[str, str], home: Path) -> Path:
        configured = env.get("OMP_AGENT_DIR", "").strip()
        if configured:
            return Path(configured)
        pi_agent_dir = env.get("PI_CODING_AGENT_DIR", "").strip()
        if pi_agent_dir:
            return Path(pi_agent_dir)
        return home / ".omp" / "agent"

    def title(self, ctx: Context) -> str:
        return f"Installing oh-my-pi config files to: {self.target_dir(ctx)}"

    def install_merged_file(self, ctx: Context, spec: FileSpec, src: Path, dst: Path) -> None:
        """Set this repo's keys in config.yml and keep the ones OMP or the user added."""
        managed = src.read_text(encoding="utf-8")
        if spec.oauth and ctx.options.oauth:
            managed = render_oauth_config(managed)
        existing = dst.read_text(encoding="utf-8") if dst.exists() else ""
        merged = yaml_merge.merge(existing, managed)
        if merged is None:
            warn(f"{dst} could not be merged (unsupported YAML); replacing it, backup kept")
            merged = managed
        ctx.files.write_text(dst, merged)

    def configure(self, ctx: Context, target: Path) -> None:
        install_models(ctx, target)
