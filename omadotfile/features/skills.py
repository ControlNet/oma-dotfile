"""Shared skills: installed once into ~/.agents/skills with the skills CLI.

OpenCode, Codex, OMP and OMO Native read ~/.agents/skills. Claude Code does not, so the
skills CLI also links each skill into its skills dir when Claude Code is installed for.
"""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import shutil
import subprocess

from omadotfile.agents.base import Component
from omadotfile.console import item, warn
from omadotfile.constants import (
    ALL_SKILLS,
    CLAUDE_CODE_EXCLUDED_SKILLS,
    OWN_SKILLS_DIR,
    REMOVED_SKILLS,
    RETIRED_SKILLS,
    SKILLS_CLI_VERSION,
    UPSTREAM_SKILLS,
)
from omadotfile.context import Context, RepoRef
from omadotfile.migration import migration

SKILLS_CLI_ENV = {"DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1"}
SKILL_COMMITS_FILE = ".oma-dotfile-skill-commits.json"
# Agents that read ~/.agents/skills and once had their own copies in <config dir>/skills.
SKILL_READERS = ("opencode", "codex", "omp", "omo")

Install = tuple[str, tuple[str, ...], tuple[str, ...]]  # (source, names, agents)


def skill_sources(repo: Path, source: RepoRef) -> dict[str, tuple[str, ...]]:
    """Map each skills CLI source to the skill names installed from it."""
    sources = dict(UPSTREAM_SKILLS)
    skills_dir = repo / OWN_SKILLS_DIR
    own = sorted(path.name for path in skills_dir.iterdir()
                 if (path / "SKILL.md").is_file()) if skills_dir.is_dir() else []
    if own:
        sources[source.skills_source] = tuple(own)
    return sources


def add_command(source: str, names: tuple[str, ...],
                agents: tuple[str, ...] = ("universal",)) -> list[str]:
    """Install names from source globally into ~/.agents/skills.

    `universal` writes only the shared copy; `claude-code` adds a link to it in Claude
    Code's skills dir, replacing a same-named entry there.
    """
    return ["npx", "-y", f"skills@{SKILLS_CLI_VERSION}", "add", source,
            "-g", "-a", *agents, "-s", *names, "-y", "--json"]


def skill_installs(repo: Path, source: RepoRef, claude: bool) -> list[Install]:
    """(source, names, agents) per skills CLI run; Claude Code skips CLAUDE_CODE_EXCLUDED_SKILLS."""
    installs = []
    for skills_source, names in skill_sources(repo, source).items():
        linked = tuple(name for name in names if not claude or name not in CLAUDE_CODE_EXCLUDED_SKILLS)
        shared = tuple(name for name in names if name not in linked)
        if linked:
            installs.append((skills_source, linked, ("universal", "claude-code") if claude else ("universal",)))
        if shared:
            installs.append((skills_source, shared, ("universal",)))
    return installs


def installed_skill_names(document: object) -> set[str]:
    """Names the skills CLI reports as installed; skipped or malformed entries do not count."""
    if not isinstance(document, list):
        return set()
    return {entry["name"] for entry in document
            if isinstance(entry, dict) and entry.get("status") == "installed"
            and isinstance(entry.get("name"), str)}


def lock_path(ctx: Context) -> Path:
    """The skills CLI's global lock file, located the way the CLI locates it."""
    state_home = ctx.env.get("XDG_STATE_HOME")
    if state_home:
        return Path(state_home) / "skills" / ".skill-lock.json"
    return ctx.home / ".agents" / ".skill-lock.json"


def locked_skills(ctx: Context) -> dict[str, dict]:
    """The skills CLI lock's entries by skill name; empty when there is no readable lock."""
    try:
        skills = json.loads(lock_path(ctx).read_text(encoding="utf-8")).get("skills")
    except (OSError, ValueError, AttributeError):
        return {}
    if not isinstance(skills, dict):
        return {}
    return {name: entry for name, entry in skills.items() if isinstance(entry, dict)}


def locked_skill_names(ctx: Context, repo: str) -> set[str]:
    """Skill names the lock records as installed from `repo` (owner/name, any case)."""
    return {name for name, entry in locked_skills(ctx).items()
            if str(entry.get("source", "")).lower() == repo.lower()}


def removable_skills(ctx: Context, names: tuple[str, ...]) -> list[str]:
    """Names among `names` that the lock records as installed from this repo."""
    ours = locked_skill_names(ctx, ctx.source.slug)
    return [name for name in names if name in ours]


def commits_path(ctx: Context) -> Path:
    """Commits of the last full install per skills CLI run, kept next to the CLI's lock."""
    return lock_path(ctx).parent / SKILL_COMMITS_FILE


def install_key(source: str, names: tuple[str, ...], agents: tuple[str, ...]) -> str:
    """Identify one skills CLI run; changing the CLI, names or agents makes it run again."""
    return f"skills@{SKILLS_CLI_VERSION} {source} -a {' '.join(agents)} -s {' '.join(names)}"


def ls_remote_commit(ctx: Context, source: str) -> str | None:
    """The commit the skills CLI would clone for `owner/repo[#ref]`, or None if unknown.

    `git ls-remote` needs no GitHub API quota and downloads no files.
    """
    repo, _, ref = source.partition("#")
    try:
        result = subprocess.run(
            ["git", "ls-remote", f"https://github.com/{repo}.git", ref or "HEAD"],
            capture_output=True, text=True, timeout=30,
            env={**ctx.env, "GIT_TERMINAL_PROMPT": "0"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    commits = {}
    for line in result.stdout.splitlines():
        commit, _, name = line.partition("\t")
        if re.fullmatch(r"[0-9a-f]{40}", commit):
            commits[name] = commit
    wanted = [f"refs/heads/{ref}", f"refs/tags/{ref}^{{}}", f"refs/tags/{ref}"] if ref else ["HEAD"]
    return next((commits[name] for name in wanted if name in commits), None)


def remote_commits(ctx: Context, sources: set[str]) -> dict[str, str]:
    """Look up every source's current commit in parallel; unknown ones are left out."""
    if not sources:
        return {}
    ordered = sorted(sources)
    with ThreadPoolExecutor(max_workers=len(ordered)) as pool:
        commits = list(pool.map(lambda source: ls_remote_commit(ctx, source), ordered))
    return {source: commit for source, commit in zip(ordered, commits) if commit}


def read_commits(ctx: Context) -> dict[str, str]:
    try:
        recorded = json.loads(commits_path(ctx).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(recorded, dict):
        return {}
    return {key: value for key, value in recorded.items() if isinstance(value, str)}


def write_commits(ctx: Context, recorded: dict[str, str]) -> None:
    path = commits_path(ctx)
    text = json.dumps(recorded, indent=2, sort_keys=True) + "\n"
    try:
        _ = ctx.files.write_text(path, text, backup=False)
    except OSError as error:
        warn(f"Could not save skill commits to {path}: {error}")


def current_skill_names(ctx: Context, source: str, names: tuple[str, ...], agents: tuple[str, ...],
                        claude_skills_dir: Path | None) -> set[str]:
    """The run's skills if all of them are still on disk, else an empty set.

    For ALL_SKILLS the names come from the lock, since only a clone lists the source.
    """
    expected = (locked_skill_names(ctx, source.partition("#")[0]) if names == (ALL_SKILLS,)
                else set(names))
    dirs = [ctx.shared_skills_dir]
    if "claude-code" in agents and claude_skills_dir is not None:
        dirs.append(claude_skills_dir)
    if expected and all((directory / name / "SKILL.md").is_file()
                        for directory in dirs for name in expected):
        return expected
    return set()


@migration(since="2026-11", reason="per-agent skill copies from before ~/.agents/skills",
           remove_by="2027-11")
def remove_legacy_skill_copies(skill_dirs: list[Path], installed: set[str]) -> None:
    """Remove per-agent copies of skills that are now installed in ~/.agents/skills.

    Agents read both places, so a leftover copy would load twice. Only names that were
    just installed (or retired in favour of one) and skills this repo dropped are touched.
    """
    names = (installed | {old for old, new in RETIRED_SKILLS.items() if new in installed}
             | set(REMOVED_SKILLS))
    for skill_dir in skill_dirs:
        for name in sorted(names):
            path = skill_dir / name
            if path.is_symlink() or path.is_file():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
            else:
                continue
            item(f"removed old copy {path}")


def ensure_skills(ctx: Context, legacy_skill_dirs: list[Path], claude_dir: Path | None = None) -> None:
    """Install the shared skills with the skills CLI, then drop the old per-agent copies.

    With claude_dir (Claude Code installed for), skills are also linked into its skills dir.
    """
    if ctx.runner.which("npx") is None:
        warn("         skills skipped: npx not found (install Node.js)")
        return
    env = dict(SKILLS_CLI_ENV)
    if claude_dir is not None:
        env["CLAUDE_CONFIG_DIR"] = str(claude_dir)
    removable = removable_skills(ctx, REMOVED_SKILLS)
    if removable and ctx.runner.ok(
            ["npx", "-y", f"skills@{SKILLS_CLI_VERSION}", "remove", *removable, "-g", "-y"], env):
        item(f"uninstalled {', '.join(removable)} (no longer shipped by this repo)")
    installs = skill_installs(ctx.repo, ctx.source, claude_dir is not None)
    # Each run clones its whole source, so one whose commit has not moved since its last
    # full install, and whose skills are all still in place, is skipped.
    commits = remote_commits(ctx, {source for source, _, _ in installs})
    recorded = read_commits(ctx)
    claude_skills_dir = claude_dir / "skills" if claude_dir is not None else None
    installed: set[str] = set()
    for source, names, agents in installs:
        key = install_key(source, names, agents)
        commit = commits.get(source)
        if commit is not None and recorded.get(key) == commit:
            current = current_skill_names(ctx, source, names, agents, claude_skills_dir)
            if current:
                item(f"{', '.join(sorted(current))} ({source}, unchanged)")
                installed |= current
                continue
        done = installed_skill_names(ctx.runner.json(add_command(source, names, agents), env))
        if done:
            also = ", also in Claude Code" if "claude-code" in agents else ""
            item(f"{', '.join(sorted(done))} ({source}{also})")
        if names == (ALL_SKILLS,):
            complete = bool(done)
            if not done:
                warn(f"Nothing installed from {source}")
        elif missing := [name for name in names if name not in done]:
            complete = False
            warn(f"Not installed from {source}: {', '.join(missing)}")
        else:
            complete = True
        if complete and commit is not None:
            recorded[key] = commit
        else:
            recorded.pop(key, None)
        installed |= done
    # Runs no longer made (a source dropped, Claude Code gone) are forgotten.
    active = {install_key(*install) for install in installs}
    write_commits(ctx, {key: value for key, value in recorded.items() if key in active})
    remove_legacy_skill_copies(legacy_skill_dirs, installed)


class Skills(Component):
    def title(self, ctx: Context) -> str:
        return "Installing shared skills to ~/.agents/skills"

    def enabled(self, ctx: Context) -> bool:
        return "claude" in ctx.found or any(key in ctx.found for key in SKILL_READERS)

    def skip_reason(self, ctx: Context) -> str:
        return "no agent that uses shared skills found"

    def configure(self, ctx: Context, target: Path | None) -> None:
        ensure_skills(ctx, [ctx.dirs[key] / "skills" for key in SKILL_READERS if key in ctx.found],
                      ctx.dirs["claude"] if "claude" in ctx.found else None)
