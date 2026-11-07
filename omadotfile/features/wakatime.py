"""WakaTime: the API settings in ~/.wakatime.cfg, and the Codex and Claude Code plugins.

OpenCode and OMP load their WakaTime integration from files installed with them, and read
only the cfg. Codex and Claude Code get the WakaTime plugin through their own plugin CLIs;
CodexPlugins and ClaudePlugins adapt those two CLIs to the one flow in ensure_plugin.
"""

from collections.abc import Mapping
from functools import partial
from pathlib import Path
import shutil

from omadotfile.console import info, success, warn
from omadotfile.constants import (
    CLAUDE_WAKATIME_MARKETPLACE_GIT_URL,
    CLAUDE_WAKATIME_MARKETPLACE_REPO,
    CLAUDE_WAKATIME_PLUGIN_ID,
    CODEX_WAKATIME_MARKETPLACE_GIT_URL,
    CODEX_WAKATIME_PLUGIN_ID,
    WAKATIME_MARKETPLACE,
)
from omadotfile.context import Context
from omadotfile.core.codec import TEXT
from omadotfile.core.errors import warns_on
from omadotfile.core.ini import set_section_keys
from omadotfile.core.proc import Runner
from omadotfile.step import found_any, step

# Installer env var -> [settings] key. wakatime-cli itself reads WAKATIME_API_KEY but
# has no env var for api_url, so a self-hosted server needs it written to the cfg.
ENV_SETTINGS = {"WAKATIME_API_URL": "api_url", "WAKATIME_API_KEY": "api_key"}
# Spellings wakatime-cli accepts in [settings]; all are replaced by the canonical key.
SETTING_ALIASES = {"api_url": ("api_url",), "api_key": ("api_key", "apikey")}
# Agents whose WakaTime integration reads the cfg.
TRACKED_AGENTS = ("opencode", "omp", "codex", "claude")


def config_path(env: Mapping[str, str], home: Path) -> Path:
    """WakaTime reads ~/.wakatime.cfg unless WAKATIME_HOME redirects it."""
    wakatime_home = env.get("WAKATIME_HOME", "").strip()
    if wakatime_home:
        return Path(wakatime_home).expanduser() / ".wakatime.cfg"
    return home / ".wakatime.cfg"


def render_config(content: str, settings: dict[str, str]) -> str:
    """Set keys in the INI [settings] section, keeping every other line as it is."""
    return set_section_keys(content, "settings", settings, SETTING_ALIASES)


def ensure_config(ctx: Context) -> None:
    """Write WAKATIME_API_URL and WAKATIME_API_KEY into the cfg, keeping other settings."""
    path = config_path(ctx.env, ctx.home)
    settings: dict[str, str] = {}
    for env_name, key in ENV_SETTINGS.items():
        value = ctx.env.get(env_name, "").strip()
        if not value:
            continue
        if "\n" in value or "\r" in value:
            warn(f"{env_name} contains a line break; not written to {path}")
            continue
        settings[key] = value

    if not settings:
        if not path.is_file() and not ctx.env.get("WAKATIME_API_KEY", "").strip():
            warn(f"WakaTime config not found: {path}; set WAKATIME_API_KEY "
                 "(and WAKATIME_API_URL for a self-hosted server) and rerun")
        return

    changed = update_config(ctx, path, settings)
    if changed is None:
        return
    if not changed:
        info(f"WakaTime config already matches the environment; skip: {path}")
        return
    # Name the keys only; their values may be secrets.
    success(f"Configured WakaTime {', '.join(settings)}: {path}")


@warns_on(OSError, ValueError, message="Failed to update {path} ({error}); leaving it unchanged")
def update_config(ctx: Context, path: Path, settings: dict[str, str]) -> bool:
    # A new file is owner-only. An existing one is made owner-only before the key is
    # written into it, or when an older run already put it there; without a key to
    # write, it keeps the mode the user chose.
    if "api_key" in settings and path.exists():
        path.chmod(0o600)
    # No backup: only env-sourced values change, and a backup would keep the old key.
    return ctx.files.update(path, TEXT, partial(render_config, settings=settings), default="",
                            backup=False, mode=0o600)


class PluginCli:
    """One agent's plugin CLI, run with the agent's config dir pinned to the installer's."""

    label: str  # the agent's name in messages
    executable: str
    dir_env: str  # the env var that points the CLI at a config dir
    plugin_id: str
    after_install: str  # what the user does next

    def __init__(self, runner: Runner, config_dir: Path):
        self.runner = runner
        self.pin = {self.dir_env: str(config_dir)}

    def json(self, command: list[str]) -> object | None:
        return self.runner.json(command, self.pin)

    def ok(self, command: list[str]) -> bool:
        return self.runner.ok(command, self.pin)

    def is_installed(self) -> bool:
        raise NotImplementedError

    def ensure_marketplace(self) -> bool:
        """Add the WakaTime marketplace, without replacing a differently sourced one."""
        raise NotImplementedError

    def install(self) -> bool:
        raise NotImplementedError


class CodexPlugins(PluginCli):
    label = "Codex"
    executable = "codex"
    dir_env = "CODEX_HOME"
    plugin_id = CODEX_WAKATIME_PLUGIN_ID
    after_install = "Approve the plugin hooks in the next Codex session to start tracking."

    def command(self, args: list[str]) -> dict | None:
        document = self.json(["codex", *args, "--json"])
        return document if isinstance(document, dict) else None

    def is_installed(self) -> bool:
        document = self.command(["plugin", "list", "--marketplace", WAKATIME_MARKETPLACE])
        if document is None:
            return False
        for entry in document.get("installed", []):
            if not isinstance(entry, dict) or entry.get("pluginId") != self.plugin_id:
                continue
            if not entry.get("installed"):
                return False
            if not entry.get("enabled"):
                # Respect a deliberate opt-out instead of re-enabling it on every run.
                warn(f'{self.plugin_id} is disabled; set enabled = true in config.toml')
            return True
        return False

    def ensure_marketplace(self) -> bool:
        document = self.command(["plugin", "marketplace", "list"])
        if document is not None:
            for entry in document.get("marketplaces", []):
                if not isinstance(entry, dict) or entry.get("name") != WAKATIME_MARKETPLACE:
                    continue
                source = (entry.get("marketplaceSource") or {}).get("source", "")
                if source == CODEX_WAKATIME_MARKETPLACE_GIT_URL:
                    return True
                warn(f"Codex marketplace '{WAKATIME_MARKETPLACE}' uses another source; "
                     "skip WakaTime plugin")
                return False
        if not self.ok(["codex", "plugin", "marketplace", "add", CODEX_WAKATIME_MARKETPLACE_GIT_URL,
                        "--json"]):
            # Codex also keeps marketplace state under .tmp/marketplaces, so a stale
            # root fails the add without showing up in the marketplace listing.
            warn(f"Stale marketplace state? Try: codex plugin marketplace remove {WAKATIME_MARKETPLACE}")
            return False
        return True

    def install(self) -> bool:
        return self.command(["plugin", "add", self.plugin_id]) is not None


class ClaudePlugins(PluginCli):
    label = "Claude Code"
    executable = "claude"
    dir_env = "CLAUDE_CONFIG_DIR"
    plugin_id = CLAUDE_WAKATIME_PLUGIN_ID
    after_install = "Restart Claude Code to load the plugin hooks."

    def is_installed(self) -> bool:
        document = self.json(["claude", "plugin", "list", "--json"])
        if not isinstance(document, list):
            return False
        for entry in document:
            if not isinstance(entry, dict) or entry.get("id") != self.plugin_id:
                continue
            if not entry.get("enabled"):
                # Respect a deliberate opt-out instead of re-enabling it on every run.
                warn(f"{self.plugin_id} is disabled; run: claude plugin enable {self.plugin_id}")
            return True
        return False

    def ensure_marketplace(self) -> bool:
        document = self.json(["claude", "plugin", "marketplace", "list", "--json"])
        if isinstance(document, list):
            for entry in document:
                if not isinstance(entry, dict) or entry.get("name") != WAKATIME_MARKETPLACE:
                    continue
                # Claude Code reports either the clone URL or the GitHub shorthand,
                # depending on how the marketplace was originally added.
                if entry.get("url") == CLAUDE_WAKATIME_MARKETPLACE_GIT_URL or \
                        entry.get("repo") == CLAUDE_WAKATIME_MARKETPLACE_REPO:
                    return True
                warn(f"Claude Code marketplace '{WAKATIME_MARKETPLACE}' uses another source; "
                     "skip WakaTime plugin")
                return False
        # This subcommand has no JSON output, so only its exit code is checked.
        return self.ok(["claude", "plugin", "marketplace", "add", CLAUDE_WAKATIME_MARKETPLACE_GIT_URL])

    def install(self) -> bool:
        # No -y: a marketplace that starts declaring an install command should stop
        # the installer instead of running that command unattended.
        document = self.json(["claude", "plugin", "install", self.plugin_id, "--json"])
        if not isinstance(document, dict) or document.get("outcome") != "ok":
            warn(f"Failed to install {self.plugin_id}")
            return False
        return True


def ensure_plugin(plugins: PluginCli) -> bool:
    """Install the WakaTime plugin; the agent CLI owns the marketplace and plugin state."""
    if plugins.runner.which(plugins.executable) is None:
        warn(f"{plugins.executable} not found; skip {plugins.label} WakaTime plugin")
        return False
    if plugins.is_installed():
        info(f"{plugins.label} WakaTime plugin already installed; skip")
        return True
    if not plugins.ensure_marketplace() or not plugins.install():
        return False
    success(f"Installed {plugins.label} plugin: {plugins.plugin_id}")
    info(plugins.after_install)
    return True


def ensure_plugins(ctx: Context) -> None:
    """Install the WakaTime plugins; each agent CLI owns its own plugin state."""
    # Both directories are created first so neither CLI is handed a missing one.
    for key in ("codex", "claude"):
        if key in ctx.found:
            ctx.dirs[key].mkdir(parents=True, exist_ok=True)
    installed = [ensure_plugin(CodexPlugins(ctx.runner, ctx.dirs["codex"])),
                 ensure_plugin(ClaudePlugins(ctx.runner, ctx.dirs["claude"]))]
    if any(installed) and shutil.which("node") is None:
        warn("node not found on PATH; the WakaTime plugin hooks require it")


@step("Configuring WakaTime config and plugins", when=found_any(*TRACKED_AGENTS),
      skip="no WakaTime-tracked agent found")
def configure_wakatime(ctx: Context) -> None:
    ensure_config(ctx)
    if found_any("codex", "claude")(ctx):
        ensure_plugins(ctx)
