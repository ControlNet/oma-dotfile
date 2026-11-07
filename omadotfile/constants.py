"""What gets installed: agents, files, skills, pinned versions and plugin ids.

Plain data only. How each thing is installed lives with the code that installs it; this module
imports nothing from the package, so every module can import it.
"""

from dataclasses import dataclass

# The repo pull.py clones; also where the skills CLI fetches this repo's own skills from.
DEFAULT_REPO_OWNER = "ControlNet"
DEFAULT_REPO_NAME = "oma-dotfile"
DEFAULT_REPO_REV = "master"

# Reported as missing at the start; the run continues without them.
REQUIRED_ENV_VARS = ("CODEX_BASE_URL", "CODEX_API_TOKEN", "GITHUB_PERSONAL_ACCESS_TOKEN")
# Not needed with --oauth, which uses each agent's own OpenAI login.
GATEWAY_ENV_VARS = ("CODEX_BASE_URL", "CODEX_API_TOKEN")

# What gets installed lives under config/, one dir per agent laid out like that agent's
# config dir (config/omp/config.yml goes to ~/.omp/agent/config.yml); files every agent gets
# sit in config/ itself. All repo paths below are relative to the repo root.
SHARED_RULES = "config/_AGENTS.md"  # not AGENTS.md: agents working in this repo must not load it
OPENCODE_CONFIG = "config/opencode/opencode.jsonc"
OMO_CONFIG = "config/omo/omo.jsonc"

# A checkout without these is not this repo.
REQUIRED_REPO_FILES = (OPENCODE_CONFIG, OMO_CONFIG)


@dataclass(frozen=True)
class FileSpec:
    """A repo file installed under an agent's config dir."""

    src: str  # path in the repo
    dst: str  # path under the agent's config dir
    managed: bool = False  # repo-owned code: replaced without a backup
    oauth: bool = False  # the agent's code writes a rewritten copy under --oauth
    merge: bool = False  # merged into the file on disk by the agent's install_merged_file


OPENCODE_FILES = (
    FileSpec(OPENCODE_CONFIG, "opencode.jsonc", oauth=True),
    FileSpec("config/opencode/tui.json", "tui.json"),
    FileSpec(SHARED_RULES, "AGENTS.md"),
)
# Each entry replaces the same-named one in <config>/plugins.
OPENCODE_PLUGINS = ("config/opencode/plugins", "plugins")  # (repo dir, dir under the config dir)

# ~/.omo/omo.jsonc, read by both the OMO OpenCode plugin and OMO Native.
OMO_FILES = (FileSpec(OMO_CONFIG, "omo.jsonc", oauth=True),)

OMO_NATIVE_FILES = (FileSpec(SHARED_RULES, "AGENTS.md"),)

OMP_FILES = (
    FileSpec("config/omp/config.yml", "config.yml", oauth=True, merge=True),  # OMP writes to it too
    # OMP loads ~/.config/opencode/AGENTS.md only when opencode is in enabledProviders, which
    # would also pull in OpenCode's plugins and MCP.
    FileSpec(SHARED_RULES, "AGENTS.md"),
    FileSpec("config/omp/extensions/omp-gotify-notify.js", "extensions/omp-gotify-notify.js", managed=True),
    FileSpec("config/omp/extensions/omp-wakatime-sync.js", "extensions/omp-wakatime-sync.js", managed=True),
)
OMP_MODELS = "config/omp/models.yml"  # gateway catalog, CODEX_BASE_URL filled in
OMP_MODELS_OAUTH = "config/omp/models.oauth.yml"  # native model overrides under --oauth
OMP_MODELS_DST = "models.yml"

CODEX_FILES = (
    FileSpec(SHARED_RULES, "AGENTS.md"),
    FileSpec("config/codex/codex-gotify-notify.py", "codex-gotify-notify.py", managed=True),
)
# Codex bundles its own copy of these, which Codex keeps using; the shared copies in
# ~/.agents/skills are switched off in Codex only, so every other agent still gets them.
CODEX_DISABLED_SHARED_SKILLS = ("skill-creator",)

CLAUDE_FILES = (FileSpec(SHARED_RULES, "rules/oma-dotfile.md"),)
CLAUDE_PLUGINS_DIR = "config/claude/plugins"  # each plugin dir goes to <config>/skills/<name>
# Empty strings hide Claude Code's own commit and PR attribution.
CLAUDE_ATTRIBUTION = {"commit": "", "pr": ""}
# Drops Claude attribution lines from every commit; installed into the global core.hooksPath.
COMMIT_MSG_HOOK = "config/git-hooks/commit-msg"

TOKSCALE_MODEL_ALIASES = "config/tokscale/model-aliases.json"

# Live workflow DAGs in a Herdr side pane (github.com/jc01rho/omo-herdr-dag). Bump on release.
OMO_HERDR_DAG_VERSION = "1.7.0"

# Shared skills go to ~/.agents/skills, which OpenCode, OMO Native, OMP and Codex all read
# (Claude Code does not). The skills CLI fetches the latest upstream on every run and records
# each skill in ~/.agents/.skill-lock.json, so `npx skills update -g` refreshes them too.
SKILLS_CLI_VERSION = "1.7.6"
ALL_SKILLS = "*"  # every skill the source has, including ones added upstream later
UPSTREAM_SKILLS = {
    "vercel-labs/skills": ("find-skills",),
    "vercel-labs/agent-skills": ("web-design-guidelines",),
    "anthropics/skills": ("frontend-design", "skill-creator"),
    "nextlevelbuilder/ui-ux-pro-max-skill": ("ui-ux-pro-max",),
    "mikubaka88/CCFA-Skills": (ALL_SKILLS,),
    "herdrdev/herdr": ("herdr",),
}
OWN_SKILLS_DIR = "skills"  # this repo's own skills, one dir with a SKILL.md each
# Old name -> the skill that replaced it; the old copy goes once the new one is installed.
RETIRED_SKILLS = {"frontend-claude": "frontend-design"}
# Skills this repo no longer ships. They are uninstalled from ~/.agents/skills while the
# skills CLI lock still says they came from this repo; a same-named skill from elsewhere stays.
REMOVED_SKILLS = ("frontend-codex",)
# Claude Code does not read ~/.agents/skills, so skills are linked into its own dir,
# except these, which overlap what Claude Code already has.
CLAUDE_CODE_EXCLUDED_SKILLS = ("skill-creator", "find-skills")

# WakaTime plugins for Codex and Claude Code. Marketplaces are added by clone URL, not by
# owner/repo shorthand: the shorthand makes the agent CLI try SSH first, which needs working
# GitHub SSH credentials.
WAKATIME_MARKETPLACE = "wakatime"
CODEX_WAKATIME_MARKETPLACE_GIT_URL = "https://github.com/wakatime/codex-cli-wakatime.git"
CODEX_WAKATIME_PLUGIN_ID = f"codex-cli-wakatime@{WAKATIME_MARKETPLACE}"
CLAUDE_WAKATIME_MARKETPLACE_GIT_URL = "https://github.com/wakatime/claude-code-wakatime.git"
CLAUDE_WAKATIME_MARKETPLACE_REPO = "wakatime/claude-code-wakatime"
CLAUDE_WAKATIME_PLUGIN_ID = f"claude-code-wakatime@{WAKATIME_MARKETPLACE}"

# Config files older versions of the agents or of this repo used. Renamed to a backup when
# found, so they no longer load (see the migrations that use them).
LEGACY_OPENCODE_JSON = "opencode.json"
LEGACY_OPENAGENT_CONFIG_NAMES = (
    "oh-my-opencode.json",
    "oh-my-opencode.jsonc",
    "oh-my-openagent.json",
    "oh-my-openagent.jsonc",
)
LEGACY_OMO_CONFIG_NAMES = ("config.json", "config.jsonc")
