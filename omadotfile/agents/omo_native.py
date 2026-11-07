"""OMO Native: AGENTS.md, the gateway provider in models.json, settings.json, omo-herdr-dag."""

from collections.abc import Mapping
from enum import Enum
from functools import partial
import json
from pathlib import Path
import re
import tarfile

from omadotfile.agents.base import Agent
from omadotfile.agents.omo import omo_dir
from omadotfile.console import info, item, warn
from omadotfile.constants import OMO_HERDR_DAG_VERSION, OMO_NATIVE_FILES
from omadotfile.context import Context
from omadotfile.core.codec import JSONC, JsonObject
from omadotfile.core.errors import Skip, skips, warns_on
from omadotfile.core.jsonc import read_jsonc_object
from omadotfile.step import requires

# omo-ai bin/lib/agent-dir.js AGENT_DIR_ENV_NAMES, most specific first.
OMO_AGENT_DIR_ENV_NAMES = ("OMO_CODING_AGENT_DIR", "SENPI_CODING_AGENT_DIR", "PI_CODING_AGENT_DIR")
# OpenCode reasoning variants that OMO Native only offers once a model maps them explicitly.
OMO_NATIVE_THINKING_LEVELS = ("low", "medium", "high", "xhigh", "max")
OMO_HERDR_DAG_MARKER = "// managed by omo-herdr-dag"
OMO_HERDR_DAG_GENERATION = re.compile(r"generation-\d+")
HERDR_DAG_LABEL = f"omo-herdr-dag {OMO_HERDR_DAG_VERSION}"


def build_gateway_provider(repo: Path, codex_base_url: str) -> dict:
    """Mirror OpenCode's `codex` gateway provider in OMO Native's models.json shape."""
    opencode = read_jsonc_object(repo / "opencode.jsonc")
    models = []
    for model_id, entry in opencode["provider"]["codex"]["models"].items():
        limit = entry.get("limit", {})
        cost = entry.get("cost", {})
        variants = entry.get("variants", {})
        models.append({
            "id": model_id,
            "reasoning": bool(entry.get("reasoning")),
            "input": entry.get("modalities", {}).get("input", ["text"]),
            # A separate input cap is what the gateway enforces, as omp_models.yaml records.
            "contextWindow": limit.get("input", limit.get("context")),
            "maxTokens": limit.get("output"),
            "cost": {
                "input": cost.get("input", 0),
                "output": cost.get("output", 0),
                "cacheRead": cost.get("cache_read", 0),
                "cacheWrite": cost.get("cache_write", 0),
            },
            "thinkingLevelMap": {
                level: variants[level].get("reasoningEffort", level)
                for level in OMO_NATIVE_THINKING_LEVELS if level in variants
            },
        })
    return {
        # The engine sends baseUrl verbatim; only apiKey and headers are interpolated.
        "baseUrl": codex_base_url,
        "api": "openai-responses",
        "apiKey": "${CODEX_API_TOKEN}",
        "models": models,
    }


def install_models(ctx: Context, agent_dir: Path) -> None:
    """Register the gateway as the `codex` provider, preserving unrelated providers."""
    if ctx.options.oauth:
        info("         OAuth mode: models.json unchanged; ChatGPT is the built-in chatgpt-subscription provider")
        return
    codex_base_url = ctx.env.get("CODEX_BASE_URL", "").strip()
    if not codex_base_url:
        warn("CODEX_BASE_URL is not set; skipping OMO Native models.json, so codex/ models stay unavailable")
        return
    if update_models(ctx, agent_dir / "models.json", codex_base_url) is not None:
        item("models.json (codex gateway provider, render CODEX_BASE_URL)")


def with_provider(name: str, provider: JsonObject, document: JsonObject) -> JsonObject:
    """models.json with `name` set to provider; other providers are kept."""
    providers = document.get("providers", {})
    if not isinstance(providers, dict):
        raise ValueError("providers must be a JSON object")
    return {**document, "providers": {**providers, name: provider}}


@warns_on(OSError, ValueError, KeyError, message="Failed to update {dst} ({error}); leaving models.json unchanged")
def update_models(ctx: Context, dst: Path, codex_base_url: str) -> bool:
    provider = build_gateway_provider(ctx.repo, codex_base_url)
    return ctx.files.update(dst, JSONC, partial(with_provider, "codex", provider))


def ensure_settings(ctx: Context, agent_dir: Path) -> None:
    """Disable the builtin rules extension, which reads ~/.claude rules and CLAUDE.md."""
    if (agent_dir / "settings.jsonc").exists():
        warn(f"{agent_dir / 'settings.jsonc'} takes precedence over settings.json; "
             'add "rules" to its disabledBuiltinExtensions by hand')
        return
    if update_settings(ctx, agent_dir / "settings.json"):
        item("settings.json (disable builtin rules extension)")


def with_extension_disabled(name: str, settings: JsonObject) -> JsonObject:
    disabled = settings.get("disabledBuiltinExtensions", [])
    if not isinstance(disabled, list):
        raise ValueError("disabledBuiltinExtensions must be a list")
    if name in disabled:
        return settings
    return {**settings, "disabledBuiltinExtensions": [*disabled, name]}


@warns_on(OSError, ValueError, message="Failed to read {dst} ({error}); leaving settings.json unchanged")
def update_settings(ctx: Context, dst: Path) -> bool:
    return ctx.files.update(dst, JSONC, partial(with_extension_disabled, "rules"))


def herdr_dag_payload(root: Path) -> dict[str, bytes] | None:
    """The files upstream's install.mjs copies from the package's dist/ into a generation."""
    try:
        files = {name: (root / name).read_bytes() for name in ("extension.mjs", "LICENSE")}
        for path in (root / "src").rglob("*"):
            if path.is_file():
                files[path.relative_to(root).as_posix()] = path.read_bytes()
    except OSError:
        return None
    return files


class InstallState(Enum):
    """What ensure_herdr_dag finds of an earlier omo-herdr-dag install."""

    MISSING = "missing"
    CURRENT = "current"  # the pinned package's files, nothing to do
    STALE = "stale"  # ours, but another version or a broken generation
    UNMANAGED = "unmanaged"  # files omo-herdr-dag did not write; never replaced


def herdr_dag_install_state(package_dist: Path, agent_dir: Path) -> InstallState:
    """Classify the installed omo-herdr-dag against the pinned package's dist/."""
    container = agent_dir / "herdr-dag" / "integration"
    wrapper = agent_dir / "extensions" / "omo-herdr-dag.js"
    try:
        wrapper_text = wrapper.read_text(encoding="utf-8") if wrapper.exists() else None
        installed_by = (container / ".installed-by").read_text(encoding="utf-8") \
            if (container / ".installed-by").exists() else None
    except (OSError, UnicodeDecodeError):
        return InstallState.UNMANAGED
    # The installer refuses to replace files it did not write; report them instead.
    if wrapper_text is not None and not wrapper_text.startswith(OMO_HERDR_DAG_MARKER):
        return InstallState.UNMANAGED
    if container.exists() and installed_by != OMO_HERDR_DAG_MARKER:
        return InstallState.UNMANAGED
    if wrapper_text is None or not container.is_dir():
        return InstallState.MISSING
    try:
        generation = json.loads((container / "current.json").read_text(encoding="utf-8"))["generation"]
    except (OSError, ValueError, KeyError, TypeError):
        return InstallState.STALE
    if not isinstance(generation, str) or not OMO_HERDR_DAG_GENERATION.fullmatch(generation):
        return InstallState.STALE
    if f"/{generation}/extension.mjs" not in wrapper_text:
        return InstallState.STALE
    expected = herdr_dag_payload(package_dist)
    if expected is not None and herdr_dag_payload(container / generation) == expected:
        return InstallState.CURRENT
    return InstallState.STALE


def tarball_from_pack(packed: object, work_dir: Path) -> Path:
    """The tarball `npm pack --json` reports writing into work_dir; Skip if it reports none."""
    match packed:
        case [{"filename": str(filename)}, *_]:
            return work_dir / Path(filename).name
        case _:
            raise Skip(f"npm pack did not report a tarball for {HERDR_DAG_LABEL}")


def extract_npm_package(tarball: Path, dest: Path) -> Path:
    """Extract an npm tarball whose members all stay under `package/`; Skip any other."""
    try:
        with tarfile.open(tarball, "r:gz") as archive:
            members = archive.getmembers()
            for member in members:
                parts = Path(member.name).parts
                if (not (member.isfile() or member.isdir()) or not parts or parts[0] != "package"
                        or ".." in parts or Path(member.name).is_absolute()):
                    raise Skip(f"Refusing {tarball.name}: unexpected member {member.name!r}")
            if hasattr(tarfile, "data_filter"):
                archive.extractall(dest, filter="data")
            else:
                archive.extractall(dest)
    except (OSError, tarfile.TarError) as exc:
        raise Skip(f"Failed to extract {tarball.name} ({type(exc).__name__})") from exc
    return dest / "package"


@requires("herdr", skip=f"         {HERDR_DAG_LABEL} skipped: herdr not found")
@requires("node", "npm", skip=f"         {HERDR_DAG_LABEL} skipped: node and npm are required")
@skips
def ensure_herdr_dag(ctx: Context, agent_dir: Path, work_dir: Path) -> None:
    """Install the pinned omo-herdr-dag with its own installer, only when its files changed.

    Each upstream install adds a generation and keeps the old ones, so an unchanged
    package is not reinstalled. No --lang is passed: the first install is English and
    later installs keep the language chosen by hand.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    cli = ctx.runner.pinned({"OMO_CODING_AGENT_DIR": str(agent_dir)})
    packed = cli.json(
        ["npm", "pack", f"omo-herdr-dag@{OMO_HERDR_DAG_VERSION}", "--pack-destination", str(work_dir), "--json"])
    package = extract_npm_package(tarball_from_pack(packed, work_dir), work_dir / "extract")
    match herdr_dag_install_state(package / "dist", agent_dir):
        case InstallState.CURRENT:
            item(f"{HERDR_DAG_LABEL} (already installed)")
        case InstallState.UNMANAGED:
            raise Skip(f"{agent_dir / 'extensions' / 'omo-herdr-dag.js'} or herdr-dag/integration was not "
                       f"written by omo-herdr-dag; leaving {HERDR_DAG_LABEL} uninstalled")
        case InstallState.MISSING | InstallState.STALE:
            item(f"{HERDR_DAG_LABEL} (Herdr DAG side pane; /reload running sessions)")
            cli.run(["node", str(package / "bin" / "omo-herdr-dag.mjs"), "install", "--agent-dir", str(agent_dir)])


class OmoNative(Agent, key="omo", label="OMO Native", executable="omo"):
    files = OMO_NATIVE_FILES

    @staticmethod
    def config_dir(env: Mapping[str, str], home: Path) -> Path:
        """The OMO Native engine state directory, found the way omo itself finds it."""
        for name in OMO_AGENT_DIR_ENV_NAMES:
            configured = env.get(name, "").strip()
            if configured:
                return Path(configured).expanduser()
        return omo_dir(home) / "agent"

    def title(self, ctx: Context) -> str:
        return f"Installing OMO Native config to: {self.target_dir(ctx)}"

    @staticmethod
    def configure(ctx: Context, target: Path) -> None:
        install_models(ctx, target)
        ensure_settings(ctx, target)
        ensure_herdr_dag(ctx, target, ctx.work / "omo-herdr-dag")
