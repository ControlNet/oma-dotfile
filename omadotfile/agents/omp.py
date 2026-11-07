"""oh-my-pi (OMP): config, AGENTS.md, Gotify and WakaTime extensions, models.yml."""

from collections.abc import Mapping
from functools import partial
import json
from pathlib import Path
import re

from omadotfile.agents.base import Agent
from omadotfile.console import info, item, warn
from omadotfile.constants import FileSpec, OMP_FILES, OMP_MODELS, OMP_MODELS_DST, OMP_MODELS_OAUTH
from omadotfile.context import Context
from omadotfile.core import yaml_merge
from omadotfile.core.codec import TEXT
from omadotfile.core.errors import warns_on
from omadotfile.core.files import Files
from omadotfile.inject import inject

BASE_URL_PLACEHOLDER = re.compile(r'^(\s*baseUrl:\s*)(["\']?)CODEX_BASE_URL\2(\s*(?:#.*)?)$', re.MULTILINE)


def render_oauth_config(content: str) -> str:
    """OMP reaches ChatGPT OAuth through its built-in `openai-codex` provider."""
    return content.replace("codex_api/", "openai-codex/")


def render_models(content: str, codex_base_url: str) -> tuple[str, bool]:
    """Render config/omp/models.yml by inlining the CODEX_BASE_URL placeholder."""
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
    content = oauth_models(ctx, ctx.repo / OMP_MODELS_OAUTH) if ctx.options.oauth else gateway_models(ctx, src)
    if content is not None:
        write_models(ctx, agent_dir / OMP_MODELS_DST, content)


@warns_on(OSError, message="Failed to read {src}: {reason}")
def oauth_models(ctx: Context, src: Path) -> str:
    item(f"{Path(OMP_MODELS_OAUTH).name} (native model overrides)")
    return src.read_text(encoding="utf-8")


@warns_on(OSError, message="Failed to read {src}: {reason}")
def gateway_models(ctx: Context, src: Path) -> str:
    """The gateway catalog with CODEX_BASE_URL inlined, or with the placeholder left in."""
    item(f"{Path(OMP_MODELS).name} (render CODEX_BASE_URL)")
    content = src.read_text(encoding="utf-8")
    codex_base_url = ctx.env.get("CODEX_BASE_URL", "").strip()
    if not codex_base_url:
        warn("CODEX_BASE_URL is not set; leaving `baseUrl: CODEX_BASE_URL` in omp models.yml. oh-my-pi will not auto-expand it.")
        return content
    content, replaced = render_models(content, codex_base_url)
    if replaced:
        info("Injected CODEX_BASE_URL into omp models.yml")
    else:
        warn("No `baseUrl: CODEX_BASE_URL` placeholder found in config/omp/models.yml")
    return content


@inject
@warns_on(OSError, message="Failed to write {dst}: {reason}")
def write_models(files: Files, /, dst: Path, content: str) -> bool:
    return files.write_text(dst, content)


class Omp(Agent, key="omp", label="oh-my-pi", executable="omp"):
    files = OMP_FILES

    @staticmethod
    def config_dir(env: Mapping[str, str], home: Path, platform: str) -> Path:
        configured = env.get("OMP_AGENT_DIR", "").strip()
        if configured:
            return Path(configured)
        pi_agent_dir = env.get("PI_CODING_AGENT_DIR", "").strip()
        if pi_agent_dir:
            return Path(pi_agent_dir)
        return home / ".omp" / "agent"

    def title(self, ctx: Context) -> str:
        return f"Installing oh-my-pi config files to: {self.target_dir(ctx)}"

    @staticmethod
    def install_merged_file(ctx: Context, spec: FileSpec, src: Path, dst: Path) -> None:
        """Set this repo's keys in config.yml and keep the ones OMP or the user added."""
        managed = src.read_text(encoding="utf-8")
        if spec.oauth and ctx.options.oauth:
            managed = render_oauth_config(managed)
        try:
            ctx.files.update(dst, TEXT, partial(yaml_merge.merge, managed=managed))
        except ValueError as exc:
            warn(f"{dst} could not be merged ({exc}); replacing it, backup kept")
            ctx.files.write_text(dst, managed)

    @staticmethod
    def configure(ctx: Context, target: Path) -> None:
        install_models(ctx, target)
