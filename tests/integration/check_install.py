"""Install this checkout the way users do and check what lands, for CI on Linux, macOS and Windows.

Each install feeds pull.py to `python -` on stdin, as the curl and PowerShell one-liners do,
with `--repo` pointing at this checkout and `--all`, so every agent's files are installed
without its CLI. Node's npx and git are real, so shared skills come from their upstream repos.

This writes to the real home directory and the global git config, so it only runs where the
`CI` environment variable is set (GitHub Actions sets it on its throwaway runners).

    python tests/integration/check_install.py
"""

from collections.abc import Iterator, Mapping
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from omadotfile.cli import AGENTS  # noqa: E402
from omadotfile.constants import CLAUDE_CODE_EXCLUDED_SKILLS, OWN_SKILLS_DIR  # noqa: E402
from omadotfile.core.jsonc import loads_jsonc_object  # noqa: E402

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    tomllib = None

# Test values, not credentials: the gateway mode needs both set, and nothing calls the model.
# `.invalid` is a reserved TLD that never resolves.
TEST_ENV = {
    "CODEX_BASE_URL": "https://gateway.invalid/v1",
    "CODEX_API_TOKEN": "ci-test-value-not-a-token",
}

# Files every --all install writes, under each agent's config dir.
EXPECTED = {
    "opencode": ("opencode.jsonc", "tui.json", "AGENTS.md",
                 "plugins/gotify-notify.js", "plugins/omo-env-remover.js"),
    "omo": ("AGENTS.md", "models.json", "settings.json"),
    "omp": ("AGENTS.md", "config.yml", "models.yml",
            "extensions/omp-gotify-notify.js", "extensions/omp-wakatime-sync.js"),
    "codex": ("AGENTS.md", "config.toml", "codex-gotify-notify.py"),
    "claude": ("settings.json", "rules/oma-dotfile.md"),
}

ANSI = re.compile(r"\x1b\[[0-9;]*m")
# Warnings that mean something the install should have done did not happen. The rest (a CLI
# or env var this runner does not have) are shown as annotations only.
BROKEN = re.compile(r"failed with exit code|Not installed from|Failed to |Source (file|directory) not found|could not be merged|placeholder found|does not parse")
ATTRIBUTION = "Claude-Session: https://claude.ai/code/session_ci_test"

failures: list[str] = []


def fail(message: str) -> None:
    failures.append(message)
    print(f"::error::{message}", flush=True)


def install(*args: str) -> str:
    """Run the bootstrap from stdin; return its output with colours removed."""
    command = [sys.executable, "-", "--repo", str(ROOT), "--all", *args]
    print(f"::group::pull.py {' '.join(['--all', *args])}", flush=True)
    result = subprocess.run(command, input=(ROOT / "pull.py").read_bytes(),
                            capture_output=True, env={**os.environ, **TEST_ENV}, check=False)
    output = ANSI.sub("", (result.stdout + result.stderr).decode("utf-8", errors="replace"))
    print(output, flush=True)
    print("::endgroup::", flush=True)
    label = f"pull.py {' '.join(args) or '(gateway)'}"
    if result.returncode != 0:
        fail(f"{label} exited with {result.returncode}")
    if "Traceback" in output:
        fail(f"{label} printed a traceback")
    for line in output.splitlines():
        if line.startswith("[ERROR]") or line.startswith("[WARN]") and BROKEN.search(line):
            fail(f"{label}: {line}")
        elif line.startswith("[WARN]"):
            print(f"::warning::{label}: {line}", flush=True)
    return output


def config_dir(key: str) -> Path:
    return AGENTS[key].config_dir(os.environ, Path.home(), sys.platform)


def hooks_dir() -> Path | None:
    result = subprocess.run(["git", "config", "--global", "--type=path", "--get", "core.hooksPath"],
                            capture_output=True, text=True, check=False)
    return Path(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip() else None


def installed_files() -> Iterator[Path]:
    """Files the installer manages, without the backups it makes along the way."""
    roots = [config_dir(key) for key in EXPECTED]
    roots += [Path.home() / ".agents", hooks_dir() or Path.home() / ".config" / "git" / "hooks"]
    for root in dict.fromkeys(roots):
        if root.is_dir():
            for path in root.rglob("*"):
                if path.is_file() and ".bak-" not in path.name and "__pycache__" not in path.parts:
                    yield path


def snapshot() -> dict[str, str]:
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in installed_files()}


def compare(before: Mapping[str, str], after: Mapping[str, str], what: str) -> None:
    changed = sorted(path for path in before.keys() | after.keys() if before.get(path) != after.get(path))
    for path in changed:
        fail(f"{what} changed {path}")


def check_quiet(output: str, what: str) -> None:
    """A run lists only what it changed, so a rerun lists nothing but unchanged summaries.

    This also catches a file rewritten with the same bytes, which a snapshot cannot see
    (each rewrite of a user file also leaves a backup).
    """
    for line in output.splitlines():
        if re.match(r" {9}- ", line) and not line.endswith(" unchanged"):
            fail(f"{what} changed something:{line[8:]}")


def check_expected_files() -> None:
    for key, names in EXPECTED.items():
        for name in names:
            path = config_dir(key) / name
            if not path.is_file():
                fail(f"missing {path}")


def check_parses() -> None:
    """Every config file in the agents' dirs must load the way the agent will load it.

    Skill dirs hold upstream content, which is not this installer's to check.
    """
    for path in installed_files():
        if path.suffix not in {".json", ".jsonc", ".toml"} or "skills" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
            if path.suffix == ".json":
                json.loads(text)
            elif path.suffix == ".jsonc":
                loads_jsonc_object(text)
            elif path.suffix == ".toml" and tomllib is not None:
                tomllib.loads(text)
        except (UnicodeDecodeError, ValueError) as exc:
            fail(f"{path} does not parse: {exc}")


def check_skills() -> None:
    """This repo's skills are in ~/.agents/skills, and linked for Claude Code."""
    claude_skills = config_dir("claude") / "skills"
    for source in sorted((ROOT / OWN_SKILLS_DIR).iterdir()):
        if not (source / "SKILL.md").is_file():
            continue
        if not (Path.home() / ".agents" / "skills" / source.name / "SKILL.md").is_file():
            fail(f"skill {source.name} missing from ~/.agents/skills")
        if source.name not in CLAUDE_CODE_EXCLUDED_SKILLS and not (claude_skills / source.name / "SKILL.md").is_file():
            fail(f"skill {source.name} missing from {claude_skills}")


def check_commit_hook(output: str) -> None:
    """A commit must still succeed, and lose its Claude attribution line when the hook is installed."""
    hooks = hooks_dir()
    hook = hooks / "commit-msg" if hooks is not None else None
    if hook is None or not hook.is_file():
        if "commit-msg hook not installed" not in output:
            fail("the commit-msg hook is neither installed nor reported as skipped")
        return
    with tempfile.TemporaryDirectory() as repo:
        def git(*args: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(["git", "-C", repo, "-c", "user.name=CI", "-c", "user.email=ci@example.invalid",
                                   *args], capture_output=True, text=True, check=False)
        _ = git("init", "-q")
        result = git("commit", "-q", "--allow-empty", "-m", f"Check the hook\n\n{ATTRIBUTION}")
        if result.returncode != 0:
            fail(f"git commit failed with the commit-msg hook installed: {result.stderr.strip()}")
            return
        message = git("log", "-1", "--format=%B").stdout
        if ATTRIBUTION in message:
            fail("the commit-msg hook kept the Claude-Session line")
        if "Check the hook" not in message:
            fail("the commit-msg hook dropped the subject line")


def main() -> int:
    if not os.environ.get("CI"):
        print("Refusing to run: this writes to the real home directory; set CI=1 on a disposable machine.")
        return 2

    first = install()
    gateway = snapshot()
    check_expected_files()
    check_parses()
    check_skills()
    check_commit_hook(first)
    check_quiet(install(), "a second gateway install")
    compare(gateway, snapshot(), "a second gateway install")

    install("--oauth")
    oauth = snapshot()
    check_expected_files()
    check_parses()
    check_quiet(install("--oauth"), "a second --oauth install")
    compare(oauth, snapshot(), "a second --oauth install")

    install()
    compare(gateway, snapshot(), "switching back from --oauth")

    if failures:
        print(f"\n{len(failures)} check(s) failed:", *failures, sep="\n  ")
        return 1
    print("\nAll install checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
