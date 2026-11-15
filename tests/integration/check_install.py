"""Install this checkout the way users do and check what lands, for CI on Linux, macOS and Windows.

Each install feeds pull.py to `python -` on stdin, as the curl and PowerShell one-liners do.
Node's npx and git are real, so shared skills come from their upstream repos.

    python tests/integration/check_install.py            # --all, on a machine without the agents
    python tests/integration/check_install.py --agents   # every agent CLI is installed
    python tests/integration/check_install.py --clone    # let pull.py clone the repo (REPO_* env)

Without `--agents`, `--all` installs every agent's files without its CLI. With `--agents`
the agents are detected, every warning outside ALLOWED_WARNINGS fails (a skipped step is a
gap in the check, not a pass), each CLI loads what was installed, and the installed
notification hooks are run against a local stand-in for Gotify.

This writes to the real home directory and the global git config, so it only runs where the
`CI` environment variable is set (GitHub Actions sets it on its throwaway runners).
"""

import argparse
from collections.abc import Iterator, Mapping
import hashlib
import http.server
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading

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
# `.invalid` is a reserved TLD that never resolves. The WakaTime key is written to
# ~/.wakatime.cfg; the plugins are installed but no agent session runs to send anything.
TEST_ENV = {
    "CODEX_BASE_URL": "https://gateway.invalid/v1",
    "CODEX_API_TOKEN": "ci-test-value-not-a-token",
    "WAKATIME_API_KEY": "ci-test-value-not-a-token",
}
GOTIFY_TEST_TOKEN = "ci-test-value-not-a-token"

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
# With --agents, the only warnings a complete install may print, each with why it is fine.
ALLOWED_WARNINGS = {
    # Printed whenever the installer sets core.hooksPath, which it does on a fresh machine.
    re.compile(r"Hooks in each repo's \.git/hooks no longer run"): "a note on setting core.hooksPath",
}

failures: list[str] = []
options = argparse.Namespace(agents=False, clone=False)


def fail(message: str) -> None:
    failures.append(message)
    print(f"::error::{message}", flush=True)


def install(*args: str) -> str:
    """Run the bootstrap from stdin; return its output with colours removed."""
    source = [] if options.clone else ["--repo", str(ROOT)]
    shown = [*([] if options.agents else ["--all"]), *args]
    print(f"::group::pull.py {' '.join(shown)}", flush=True)
    result = subprocess.run([sys.executable, "-", *source, *shown], input=(ROOT / "pull.py").read_bytes(),
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
        elif line.startswith("[WARN]") and options.agents and not any(p.search(line) for p in ALLOWED_WARNINGS):
            fail(f"{label} warned with every agent installed: {line}")
        elif line.startswith("[WARN]"):
            print(f"::warning::{label}: {line}", flush=True)
    # Only a --repo checkout is named; pull.py's temporary clone is not.
    if options.clone and "Using repository: " in output:
        fail(f"{label} used a local checkout instead of cloning")
    if options.agents:
        check_detected(output, label)
    return output


def check_detected(output: str, label: str) -> None:
    detected = next((line for line in output.splitlines() if line.startswith("[INFO]    Detected: ")), "")
    found = set(detected.removeprefix("[INFO]    Detected: ").split(", "))
    for agent in AGENTS.values():
        if agent.label not in found:
            fail(f"{label} did not detect {agent.label}")


def config_dir(key: str) -> Path:
    return AGENTS[key].config_dir(os.environ, Path.home(), sys.platform)


def hooks_dir() -> Path | None:
    # Git prints UTF-8; text=True would decode with the Windows code page and garble a home
    # such as "Zoë Example" (the installer's Runner decodes UTF-8 too).
    result = subprocess.run(["git", "config", "--global", "--type=path", "--get", "core.hooksPath"],
                            capture_output=True, encoding="utf-8", errors="replace", check=False)
    return Path(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip() else None


def installed_files() -> Iterator[Path]:
    """Files the installer manages, without the backups it makes along the way."""
    roots = [config_dir(key) for key in AGENTS]
    roots += [Path.home() / ".agents", Path.home() / ".gemini" / "config",
              hooks_dir() or Path.home() / ".config" / "git" / "hooks"]
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
    """A run lists only what it changed, so a rerun lists nothing but unchanged summaries
    and reports no success but the last.

    This also catches a file rewritten with the same bytes, which a snapshot cannot see
    (each rewrite of a user file also leaves a backup).
    """
    for line in output.splitlines():
        if re.match(r" {9}- ", line) and not line.endswith(" unchanged"):
            fail(f"{what} changed something:{line[8:]}")
        elif line.startswith("[SUCCESS]") and line != "[SUCCESS] Installation complete!":
            fail(f"{what} changed something: {line}")


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
    with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as bare_bin:
        def git(*args: str, env: Mapping[str, str] | None = None) -> subprocess.CompletedProcess[str]:
            return subprocess.run(["git", "-C", repo, "-c", "user.name=CI", "-c", "user.email=ci@example.invalid",
                                   *args], capture_output=True, encoding="utf-8", errors="replace", env=env,
                                  check=False)

        def check_commit(subject: str, env: Mapping[str, str] | None = None) -> None:
            result = git("commit", "-q", "--allow-empty", "-m", f"{subject}\n\n{ATTRIBUTION}", env=env)
            if result.returncode != 0:
                fail(f"git commit ({subject}) failed with the commit-msg hook installed: {result.stderr.strip()}")
                return
            message = git("log", "-1", "--format=%B").stdout
            if ATTRIBUTION in message:
                fail(f"the commit-msg hook kept the Claude-Session line ({subject})")
            if subject not in message:
                fail(f"the commit-msg hook dropped the subject line ({subject})")

        _ = git("init", "-q")
        check_commit("Check the hook")
        # A GUI client, an IDE or cron may commit with a PATH that has no Python on it (and on
        # Windows `python3` is often only the Store's alias, which exits non-zero).
        check_commit("Check the hook without Python on PATH", {**os.environ, "PATH": path_without_python(Path(bare_bin))})


def git_cmd_dir(git: Path) -> Path:
    """Git for Windows' cmd dir, from any of its git.exe (cmd, bin, mingw64\\bin)."""
    return next((root / "cmd" for root in git.parents if (root / "cmd" / "git.exe").is_file()), git.parent)


def path_without_python(bare_bin: Path) -> str:
    """A PATH with git on it and no Python."""
    git = Path(shutil.which("git") or "git").resolve()
    if sys.platform == "win32":
        # The dir Git for Windows puts on PATH, plus its usr\\bin, where the sh that runs hooks
        # lives; neither holds a Python. cmd\\git.exe adds usr\\bin itself, but not when
        # MSYSTEM is set, as it is under Git Bash.
        cmd = git_cmd_dir(git)
        path = os.pathsep.join([str(cmd), str(cmd.parent / "usr" / "bin")])
    else:
        (bare_bin / "git").symlink_to(git)
        path = str(bare_bin)
    if not shutil.which("git", path=path):
        fail(f"{path} for the Python-less commit has no git on it")
    for python in ("python3", "python"):
        if shutil.which(python, path=path):
            fail(f"{path} for the Python-less commit has {python} on it")
    return path


def run_cli(name: str, *args: str) -> subprocess.CompletedProcess[str] | None:
    """Run an agent CLI found on PATH (npm installs `.cmd` shims on Windows)."""
    executable = shutil.which(name)
    if executable is None:
        fail(f"{name} is not on PATH")
        return None
    result = subprocess.run([executable, *args], capture_output=True, text=True, encoding="utf-8",
                            errors="replace", stdin=subprocess.DEVNULL, timeout=300, check=False)
    print(f"::group::{name} {' '.join(args)} (exit {result.returncode})\n{result.stdout}{result.stderr}\n::endgroup::",
          flush=True)
    if result.returncode != 0:
        fail(f"{name} {' '.join(args)} exited with {result.returncode}")
    return result


def json_in(text: str) -> object:
    """The JSON document in a CLI's stdout, after any warning lines it prints first."""
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    try:
        return json.loads(text[min(starts):]) if starts else None
    except ValueError:
        return None


def check_agent_clis() -> None:
    """Each agent loads the config that was installed; a broken one makes these fail.

    Each command below was checked to fail (or, for omo and Claude Code, to report it as
    shown) when the file it reads is broken.
    """
    if (result := run_cli("codex", "features", "list")) is None:
        return
    plugins = json_in(getattr(run_cli("codex", "plugin", "list", "--json"), "stdout", ""))
    entries = plugins.get("installed", []) if isinstance(plugins, dict) else []
    if not any(isinstance(e, dict) and e.get("pluginId") == "codex-cli-wakatime@wakatime" and e.get("enabled")
               for e in entries):
        fail("codex does not list the WakaTime plugin as installed and enabled")

    result = run_cli("opencode", "debug", "config")
    if result is not None and "gotify-notify.js" not in result.stdout:
        fail("opencode debug config does not load the gotify-notify plugin")

    _ = run_cli("omp", "config", "list")

    result = run_cli("omo", "--list-models")
    if result is not None:
        output = result.stdout + result.stderr
        for line in output.splitlines():
            if line.startswith("Warning:"):
                fail(f"omo --list-models: {line}")
        if not re.search(r"^codex\s", result.stdout, re.MULTILINE):
            fail("omo --list-models does not list the codex provider from models.json")

    # A settings.json Claude Code cannot read leaves every plugin listed as disabled.
    listed = json_in(getattr(run_cli("claude", "plugin", "list", "--json"), "stdout", ""))
    enabled = {e.get("id") for e in listed if isinstance(e, dict) and e.get("enabled")} \
        if isinstance(listed, list) else set()
    for plugin in ("claude-code-wakatime@wakatime", "gotify-notify@skills-dir"):
        if plugin not in enabled:
            fail(f"claude plugin list does not show {plugin} enabled")

    for path in (Path.home() / ".gemini" / "config" / "skills.json",
                 config_dir("omo") / "extensions" / "omo-herdr-dag.js",
                 config_dir("tokscale") / "settings.json"):
        if not path.is_file():
            fail(f"missing {path}")


class GotifyStandIn(http.server.ThreadingHTTPServer):
    """Records the messages posted to it, on a free local port."""

    def __init__(self) -> None:
        self.messages: list[tuple[str, str, dict[str, object]]] = []
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                server.messages.append((self.path, self.headers.get("X-Gotify-Key") or "", json.loads(body)))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                _ = self.wfile.write(b'{"id": 1}')

            def log_message(self, format: str, *args: object) -> None:
                pass

        super().__init__(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"


def run_hook(what: str, command: list[str], gotify: GotifyStandIn, expected: str, payload: str | None = None) -> None:
    """Run an installed hook the way its agent does and expect one message, with `expected` in it."""
    executable = Path(command[0])
    # The agents start hooks without a shell, so a bare `python3` would depend on PATH.
    if not executable.is_absolute() or not executable.is_file():
        fail(f"{what} runs {command[0]}, not an absolute path to an interpreter")
        return
    before = len(gotify.messages)
    env = {**os.environ, "GOTIFY_URL": gotify.url,
           "GOTIFY_TOKEN_FOR_CLAUDE": GOTIFY_TEST_TOKEN, "GOTIFY_TOKEN_FOR_CODEX": GOTIFY_TEST_TOKEN}
    result = subprocess.run(command, input=payload, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", env=env, timeout=60, check=False)
    if result.returncode != 0:
        fail(f"{what} exited with {result.returncode}: {result.stderr.strip()[-500:]}")
    sent = gotify.messages[before:]
    if [(path, key) for path, key, _ in sent] != [("/message", GOTIFY_TEST_TOKEN)]:
        fail(f"{what} posted {sent} instead of one message")
        return
    text = str(sent[0][2].get("message"))
    if expected not in text:
        fail(f"{what} posted {text!r}, without {expected!r}")
    # ascii(): the log shows each character as sent, not as the code page can print it.
    print(f"{what} posted: {ascii(sent[0][2])}", flush=True)


def check_notify_hooks() -> None:
    """The installed Claude Code and Codex notification hooks deliver a message."""
    gotify = GotifyStandIn()
    try:
        plugin = config_dir("claude") / "skills" / "gotify-notify"
        hooks = json.loads((plugin / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        hook = hooks["Stop"][0]["hooks"][0]
        command = [hook["command"], *(arg.replace("${CLAUDE_PLUGIN_ROOT}", str(plugin)) for arg in hook.get("args", []))]
        run_hook("the Claude Code Stop hook", command, gotify, "Response finished: CI checked the Stop hook.", json.dumps({
            "hook_event_name": "Stop", "session_id": "ci-session", "prompt_id": "ci-prompt",
            "cwd": str(ROOT), "last_assistant_message": "CI checked the Stop hook."}))

        config = (config_dir("codex") / "config.toml").read_text(encoding="utf-8")
        line = next((line for line in config.splitlines() if line.startswith("notify = ")), None)
        if line is None:
            fail("config.toml has no top-level notify line")
            return
        # The installer writes each element with toml_basic_string, which is JSON.
        notify = json.loads(line.removeprefix("notify = "))
        run_hook("the Codex notify command", [*notify, json.dumps({
            "type": "agent-turn-complete", "thread-id": "ci-thread", "input-messages": ["check"],
            "last-assistant-message": "CI checked the notify command."})], gotify,
            "\u2705 CI checked the notify command.")
    finally:
        gotify.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--agents", action="store_true", help="every agent CLI is installed on this machine")
    parser.add_argument("--clone", action="store_true", help="let pull.py clone the repo instead of --repo")
    _ = parser.parse_args(namespace=options)
    # The CLIs print characters a Windows code page lacks; a log line is not worth a crash.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="replace")
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

    # Last: the CLIs and hooks write their own state into the dirs the snapshots cover.
    if options.agents:
        check_agent_clis()
        check_notify_hooks()

    if failures:
        print(f"\n{len(failures)} check(s) failed:", *failures, sep="\n  ")
        return 1
    print("\nAll install checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
