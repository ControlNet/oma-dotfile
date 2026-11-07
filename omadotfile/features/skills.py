"""Shared skills: installed once into ~/.agents/skills with the skills CLI.

OpenCode, Codex, OMP and OMO Native read ~/.agents/skills. Claude Code does not, so the
skills CLI also links each skill into its skills dir when Claude Code is installed for.
"""

from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
from pathlib import Path
import re
import shutil
import subprocess

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
from omadotfile.core.errors import skips, warns_on
from omadotfile.core.proc import Runner
from omadotfile.migration import migration
from omadotfile.step import found_any, requires, step

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
    _ = save_commits(ctx, commits_path(ctx), json.dumps(recorded, indent=2, sort_keys=True) + "\n")


@warns_on(OSError, message="Could not save skill commits to {path}: {reason}")
def save_commits(ctx: Context, path: Path, text: str) -> bool:
    return ctx.files.write_text(path, text, backup=False)


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


def legacy_copy_names(installed: set[str]) -> list[str]:
    """Names whose per-agent copies go: the installed skills, the ones they retire, and
    the skills this repo dropped."""
    retired = {old for old, new in RETIRED_SKILLS.items() if new in installed}
    return sorted(installed | retired | set(REMOVED_SKILLS))


@migration(since="2026-11", reason="per-agent skill copies from before ~/.agents/skills",
           remove_by="2027-11")
def remove_legacy_skill_copies(skill_dirs: list[Path], installed: set[str]) -> None:
    """Remove per-agent copies of skills that are now installed in ~/.agents/skills.

    Agents read both places, so a leftover copy would load twice. Only names that were
    just installed (or retired in favour of one) and skills this repo dropped are touched.
    """
    for path in (skill_dir / name for skill_dir in skill_dirs for name in legacy_copy_names(installed)):
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
        else:
            continue
        item(f"removed old copy {path}")


@dataclass(frozen=True)
class InstallResult:
    """One skills CLI run's outcome: the skills now in place, and the commit to record."""

    key: str  # install_key of the run
    done: frozenset[str]
    commit: str | None  # None: the run is forgotten, so the next install makes it again


def recorded_commits(results: Iterable[InstallResult]) -> dict[str, str]:
    """The commit record after this install: one entry per run that is complete at a known commit.

    Every run of this install has a result, so runs no longer made (a source dropped,
    Claude Code gone) drop out of the record with no extra step.
    """
    return {result.key: result.commit for result in results if result.commit is not None}


def incomplete(source: str, names: tuple[str, ...], done: frozenset[str]) -> str | None:
    """Why a run left skills out, or None when it installed all it was asked for."""
    if names == (ALL_SKILLS,):
        return None if done else f"Nothing installed from {source}"
    missing = [name for name in names if name not in done]
    return f"Not installed from {source}: {', '.join(missing)}" if missing else None


@skips
def uninstall(cli: Runner, names: list[str]) -> None:
    """Uninstall skills from ~/.agents/skills; a failure is warned about and the install goes on."""
    cli.run(["npx", "-y", f"skills@{SKILLS_CLI_VERSION}", "remove", *names, "-g", "-y"])
    item(f"uninstalled {', '.join(names)} (no longer shipped by this repo)")


@skips
def add_skills(cli: Runner, source: str, names: tuple[str, ...], agents: tuple[str, ...]) -> frozenset[str]:
    """Run the skills CLI once; the names it installed. A failed run is warned about (None)."""
    return frozenset(installed_skill_names(cli.json(add_command(source, names, agents))))


@requires("npx", skip="         skills skipped: npx not found (install Node.js)")
def ensure_skills(ctx: Context, legacy_skill_dirs: list[Path], claude_dir: Path | None = None) -> None:
    """Install the shared skills with the skills CLI, then drop the old per-agent copies.

    With claude_dir (Claude Code installed for), skills are also linked into its skills dir.
    """
    cli = ctx.runner.pinned(SKILLS_CLI_ENV)
    if claude_dir is not None:
        cli = cli.pinned({"CLAUDE_CONFIG_DIR": str(claude_dir)})
    removable = removable_skills(ctx, REMOVED_SKILLS)
    if removable:
        uninstall(cli, removable)
    installs = skill_installs(ctx.repo, ctx.source, claude_dir is not None)
    # Each run clones its whole source, so one whose commit has not moved since its last
    # full install, and whose skills are all still in place, is skipped.
    commits = remote_commits(ctx, {source for source, _, _ in installs})
    recorded = read_commits(ctx)
    claude_skills_dir = claude_dir / "skills" if claude_dir is not None else None

    def install_or_reuse(install: Install) -> InstallResult:
        source, names, agents = install
        key = install_key(*install)
        commit = commits.get(source)
        if commit is not None and recorded.get(key) == commit:
            current = current_skill_names(ctx, source, names, agents, claude_skills_dir)
            if current:
                item(f"{', '.join(sorted(current))} ({source}, unchanged)")
                return InstallResult(key, frozenset(current), commit)
        done = add_skills(cli, source, names, agents) or frozenset()
        if done:
            also = ", also in Claude Code" if "claude-code" in agents else ""
            item(f"{', '.join(sorted(done))} ({source}{also})")
        if (reason := incomplete(source, names, done)) is not None:
            warn(reason)
            return InstallResult(key, done, None)
        return InstallResult(key, done, commit)

    results = [install_or_reuse(install) for install in installs]
    write_commits(ctx, recorded_commits(results))
    remove_legacy_skill_copies(legacy_skill_dirs, set[str]().union(*(result.done for result in results)))


@step("Installing shared skills to ~/.agents/skills", when=found_any("claude", *SKILL_READERS),
      skip="no agent that uses shared skills found")
def install_shared_skills(ctx: Context) -> None:
    ensure_skills(ctx, [ctx.dirs[key] / "skills" for key in SKILL_READERS if key in ctx.found],
                  ctx.dirs["claude"] if "claude" in ctx.found else None)
