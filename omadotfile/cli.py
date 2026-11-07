"""Entry point: detect the agents, then run each install step in order."""

import argparse
from collections.abc import Mapping, Sequence
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from omadotfile.agents.base import Agent
from omadotfile.agents.claude import Claude
from omadotfile.agents.codex import Codex
from omadotfile.agents.omo import OmoConfig
from omadotfile.agents.omo_native import OmoNative
from omadotfile.agents.omp import Omp
from omadotfile.agents.opencode import OpenCode
from omadotfile.agents.tokscale import Tokscale
from omadotfile.console import BANNER, error, info, step, success, warn
from omadotfile.constants import GATEWAY_ENV_VARS, REQUIRED_ENV_VARS, REQUIRED_REPO_FILES
from omadotfile.context import Context, Options, RepoRef
from omadotfile.features.skills import install_shared_skills
from omadotfile.features.wakatime import configure_wakatime
from omadotfile.step import Step

# One instance per agent, in the order agents are detected and reported.
AGENTS: dict[str, Agent] = {agent.key: agent for agent in (
    OpenCode(), OmoNative(), Omp(), Codex(), Claude(), Tokscale(),
)}

# The install steps, run in this order and numbered from 1.
STEPS: tuple[Step, ...] = (
    AGENTS["opencode"],
    OmoConfig(),
    AGENTS["omo"],
    AGENTS["omp"],
    AGENTS["codex"],
    configure_wakatime,
    AGENTS["claude"],
    AGENTS["tokscale"],
    install_shared_skills,
)

# What to run after --oauth to log in to each agent.
OAUTH_LOGINS = {
    "codex": "codex login",
    "opencode": "opencode auth login --provider openai",
    "omo": "omo /login chatgpt-subscription",
    "omp": "OMP /login openai-codex",
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync agent configurations from GitHub.")
    parser.add_argument("--oauth", action="store_true",
                        help="Use native OpenAI OAuth routing; log in separately in each agent.")
    parser.add_argument("--all", dest="install_all", action="store_true",
                        help="Install every target even if its agent is not detected.")
    return parser.parse_args(argv)


def warn_missing_required_env_vars(env: Mapping[str, str], oauth: bool = False) -> None:
    missing = [
        name for name in REQUIRED_ENV_VARS
        if not (oauth and name in GATEWAY_ENV_VARS) and not env.get(name, "").strip()
    ]
    if not missing:
        info("All required environment variables are present")
        return

    info("Missing required environment variables from README:")
    for name in missing:
        info(f"  - {name}")
    info("Script will continue, but related features may not work as expected.")


def detect_agents(env: Mapping[str, str], home: Path, platform: str, force: bool = False) -> frozenset[str]:
    """Keys of the agents whose software is present, so only their config gets installed."""
    return frozenset(key for key, agent in AGENTS.items() if force or agent.detect(env, home, platform))


def report_agents(found: frozenset[str], forced: bool = False) -> None:
    """Show which agents were detected and which are skipped as not installed."""
    if forced:
        info("Installing every target without detection (--all)")
        return
    detected = [agent.label for key, agent in AGENTS.items() if key in found]
    missing = [agent.label for key, agent in AGENTS.items() if key not in found]
    info(f"Detected: {', '.join(detected)}" if detected else "Detected: nothing")
    if missing:
        warn(f"Not installed, skipping: {', '.join(missing)}")
        info("Use --all (or INSTALL_ALL=1) to install these anyway.")


def done_notes(ctx: Context) -> list[str]:
    """What to do next and where the backups are, one line each."""
    notes = []
    if ctx.options.oauth:
        notes.append("OAuth routing installed; model IDs and reasoning levels are unchanged.")
        logins = [command for key, command in OAUTH_LOGINS.items() if key in ctx.found]
        if logins:
            notes.append(f"Log in with: {'; '.join(logins)}")
        notes.append("Check each agent's model list. Existing profiles, explicit model choices, and resumed sessions may override defaults.")
    notes.append(f"Timestamp: {ctx.stamp}")
    if ctx.options.backup:
        notes.append(f"Backups: *.bak-{ctx.stamp} (keep last {ctx.options.max_backups} per file)")
    return notes


def report_done(ctx: Context) -> None:
    print()
    success("Installation complete!")
    for note in done_notes(ctx):
        info(note)


def run_steps(ctx: Context) -> None:
    total = len(STEPS)
    for number, current in enumerate(STEPS, start=1):
        enabled = current.enabled(ctx)
        if step(f"{number}/{total}", current.title(ctx), enabled,
                "" if enabled else current.skip_reason(ctx)):
            current.run(ctx)


def main(argv: Sequence[str] | None = None, repo: Path | None = None,
         env: Mapping[str, str] | None = None, home: Path | None = None) -> Context:
    """Install from the checkout at repo (by default, the one this package is in)."""
    args = parse_args(argv)
    env = dict(os.environ if env is None else env)
    home = Path.home() if home is None else home
    repo = Path(__file__).resolve().parent.parent if repo is None else repo
    options = Options.from_env(env, oauth=args.oauth, install_all=args.install_all)

    print(BANNER)
    warn_missing_required_env_vars(env, oauth=options.oauth)
    found = detect_agents(env, home, sys.platform, force=options.install_all)
    report_agents(found, forced=options.install_all)

    info(f"Using repository: {repo}")
    for name in REQUIRED_REPO_FILES:
        if not (repo / name).is_file():
            error(f"Required repository file is missing: {name}")
            sys.exit(1)

    with TemporaryDirectory() as work:
        ctx = Context(
            repo=repo,
            work=Path(work),
            options=options,
            env=env,
            home=home,
            python=sys.executable or "python3",
            source=RepoRef.from_env(env),
            found=found,
            dirs={key: agent.config_dir(env, home, sys.platform) for key, agent in AGENTS.items()},
        )
        run_steps(ctx)
    report_done(ctx)
    return ctx
