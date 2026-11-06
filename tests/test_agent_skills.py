"""Shared agent skill install tests.

Repos, agent skill directories and skills CLI JSON replies are synthetic stand-ins in
temporary directories. npx and the skills CLI are never run.
"""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pull_agent_skills", ROOT / "pull.py")
assert SPEC is not None and SPEC.loader is not None
pull = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pull)

REPO_SOURCE = f"{pull.REPO_OWNER}/{pull.REPO_NAME}#{pull.REPO_REV}"


def write_skill(root: Path, name: str, text: str = "kept\n") -> Path:
    path = root / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_text(text, encoding="utf-8")
    return path


def cli_reply(installed: tuple[str, ...] = (), skipped: tuple[str, ...] = ()) -> list[dict]:
    """A skills CLI `add --json` reply in the shape skills 1.7.6 prints."""
    reply: list[dict] = [{"name": name, "status": "skipped", "reason": "No matching skill found in source"}
                         for name in skipped]
    reply.extend({"name": name, "status": "installed", "scope": "global", "mode": "copy"}
                 for name in installed)
    return reply


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.repo = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_repo_skills_are_installed_from_this_repo_at_the_cloned_ref(self):
        # Given repo skills, a folder without SKILL.md, and a stray file.
        for name in ("secret-guard", "github-cli"):
            write_skill(self.repo / "skills", name)
        (self.repo / "skills" / "notes").mkdir()
        _ = (self.repo / "skills" / "README.md").write_text("not a skill\n", encoding="utf-8")
        # Then only real skills are installed, from GitHub at the cloned branch.
        sources = pull.agent_skill_sources(self.repo)
        self.assertEqual(sources[REPO_SOURCE], ("github-cli", "secret-guard"))
        # And the upstream skills come from their own repos.
        for source, names in pull.UPSTREAM_SKILLS.items():
            self.assertEqual(sources[source], names)

    def test_repo_without_skills_installs_only_upstream(self):
        self.assertEqual(pull.agent_skill_sources(self.repo), pull.UPSTREAM_SKILLS)

    def test_upstream_replaces_the_retired_vendored_copies(self):
        upstream = {name for names in pull.UPSTREAM_SKILLS.values() for name in names}
        self.assertEqual(upstream, {"find-skills", "web-design-guidelines", "frontend-design",
                                    "skill-creator", "ui-ux-pro-max"})
        self.assertEqual(pull.RETIRED_SKILLS, {"frontend-claude": "frontend-design"})
        for name in (*upstream, "frontend-claude"):
            self.assertFalse((ROOT / "skills" / name).exists(), name)

    def test_add_command_installs_globally_into_the_shared_dir_only(self):
        command = pull.skills_cli_add_command("vercel-labs/skills", ("find-skills",))
        self.assertEqual(command, [
            "npx", "-y", f"skills@{pull.SKILLS_CLI_VERSION}", "add", "vercel-labs/skills",
            "-g", "-a", "universal", "-s", "find-skills", "-y", "--json",
        ])


class InstalledNamesTests(unittest.TestCase):
    def test_only_installed_entries_count(self):
        reply = cli_reply(installed=("skill-creator",), skipped=("frontend-design",))
        self.assertEqual(pull.installed_skill_names(reply), {"skill-creator"})

    def test_unexpected_replies_install_nothing(self):
        for reply in (None, {}, "installed", [None, {"status": "installed"}, {"name": 1, "status": "installed"}]):
            self.assertEqual(pull.installed_skill_names(reply), set(), reply)


class AgentSkillsHarness(unittest.TestCase):
    """Fake npx, CLI replies and lock file; holds no tests itself."""

    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.repo = self.tmp / "repo"
        write_skill(self.repo / "skills", "github-cli")
        self.legacy = [self.tmp / "opencode" / "skills", self.tmp / "codex" / "skills"]
        self.npx = self.enterContext(patch.object(pull, "find_agent_executable",
                                                  return_value=Path("/fake/bin/npx")))
        self.replies: dict[str, object] = {}
        self.cli = self.enterContext(patch.object(pull, "read_plugin_json", side_effect=self.reply))
        self.lock = self.tmp / "state" / ".skill-lock.json"
        self.enterContext(patch.object(pull, "skills_lock_path", return_value=self.lock))
        self.remove = self.enterContext(patch.object(pull, "run_plugin_command", return_value=True))

    def write_lock(self, sources: dict[str, str]) -> None:
        self.lock.parent.mkdir(parents=True, exist_ok=True)
        skills = {name: {"source": source, "sourceType": "github"} for name, source in sources.items()}
        _ = self.lock.write_text(json.dumps({"version": 3, "skills": skills}), encoding="utf-8")

    def reply(self, command, *args, **kwargs):
        return self.replies.get(command[4])

    def run_install(self) -> str:
        with contextlib.redirect_stdout(io.StringIO()) as out, \
                contextlib.redirect_stderr(io.StringIO()) as err:
            pull.ensure_agent_skills(self.repo, self.legacy)
        return out.getvalue() + err.getvalue()


class EnsureAgentSkillsTests(AgentSkillsHarness):
    def test_each_source_runs_with_telemetry_off(self):
        self.run_install()
        sources = [call.args[0][4] for call in self.cli.call_args_list]
        self.assertEqual(sources, [*pull.UPSTREAM_SKILLS, REPO_SOURCE])
        for call in self.cli.call_args_list:
            self.assertEqual(call.kwargs["extra_env"], {"DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1"})

    def test_installed_skills_leave_the_agent_dirs_and_others_stay(self):
        # Given old copies in two agent dirs, next to the user's own skill.
        stale = [write_skill(d, name) for d in self.legacy
                 for name in ("find-skills", "github-cli", "frontend-claude")]
        own = write_skill(self.legacy[0], "my-skill")
        not_installed = write_skill(self.legacy[1], "ui-ux-pro-max")
        # When the CLI installs all but ui-ux-pro-max.
        self.replies = {
            "vercel-labs/skills": cli_reply(installed=("find-skills",)),
            "anthropics/skills": cli_reply(installed=("frontend-design", "skill-creator")),
            "nextlevelbuilder/ui-ux-pro-max-skill": cli_reply(skipped=("ui-ux-pro-max",)),
            REPO_SOURCE: cli_reply(installed=("github-cli",)),
        }
        output = self.run_install()
        # Then the installed names and the retired frontend-claude are gone.
        for path in stale:
            self.assertFalse(path.parent.exists(), path)
        # And the user's skill and the one that failed to install are untouched.
        self.assertEqual(own.read_text(encoding="utf-8"), "kept\n")
        self.assertEqual(not_installed.read_text(encoding="utf-8"), "kept\n")
        self.assertIn("ui-ux-pro-max", output)

    def test_retired_name_stays_until_its_replacement_installs(self):
        old = write_skill(self.legacy[0], "frontend-claude")
        self.replies = {"anthropics/skills": cli_reply(installed=("skill-creator",), skipped=("frontend-design",))}
        self.run_install()
        self.assertTrue(old.is_file())

    def test_linked_copy_is_unlinked_without_touching_its_target(self):
        target = write_skill(self.tmp / "elsewhere", "find-skills")
        self.legacy[0].mkdir(parents=True)
        (self.legacy[0] / "find-skills").symlink_to(target.parent, target_is_directory=True)
        self.replies = {"vercel-labs/skills": cli_reply(installed=("find-skills",))}
        self.run_install()
        self.assertFalse((self.legacy[0] / "find-skills").is_symlink())
        self.assertTrue(target.is_file())

    def test_failed_cli_run_removes_nothing(self):
        old = write_skill(self.legacy[0], "find-skills")
        self.replies = {}
        self.run_install()
        self.assertTrue(old.is_file())

    def test_missing_agent_dirs_are_not_created(self):
        self.replies = {"vercel-labs/skills": cli_reply(installed=("find-skills",))}
        self.run_install()
        for path in self.legacy:
            self.assertFalse(path.exists(), path)

    def test_without_npx_nothing_runs_or_is_removed(self):
        old = write_skill(self.legacy[0], "find-skills")
        self.npx.return_value = None
        output = self.run_install()
        self.cli.assert_not_called()
        self.assertTrue(old.is_file())
        self.assertIn("npx", output)


class RemovedSkillTests(AgentSkillsHarness):
    """Skills dropped from this repo are uninstalled from ~/.agents/skills."""

    def test_frontend_codex_is_no_longer_shipped(self):
        self.assertIn("frontend-codex", pull.REMOVED_SKILLS)
        self.assertFalse((ROOT / "skills" / "frontend-codex").exists())
        self.assertNotIn("frontend-codex", pull.agent_skill_sources(ROOT).get(REPO_SOURCE, ()))

    def test_skill_installed_from_this_repo_is_removed_with_the_cli(self):
        self.write_lock({"frontend-codex": f"{pull.REPO_OWNER}/{pull.REPO_NAME}", "ccf-common": "someone/else"})
        output = self.run_install()
        command = self.remove.call_args.args[0]
        self.assertEqual(command, ["npx", "-y", f"skills@{pull.SKILLS_CLI_VERSION}", "remove",
                                   "frontend-codex", "-g", "-y"])
        self.assertEqual(self.remove.call_args.kwargs["extra_env"], pull.SKILLS_CLI_ENV)
        self.assertIn("frontend-codex", output)

    def test_same_name_from_another_source_is_kept(self):
        self.write_lock({"frontend-codex": "someone/else"})
        self.run_install()
        self.remove.assert_not_called()

    def test_nothing_to_remove_without_a_lock(self):
        self.run_install()
        self.remove.assert_not_called()

    def test_unreadable_lock_removes_nothing(self):
        self.lock.parent.mkdir(parents=True)
        _ = self.lock.write_text("{not json", encoding="utf-8")
        self.run_install()
        self.remove.assert_not_called()

    def test_old_per_agent_copies_go_even_when_nothing_installs(self):
        old = write_skill(self.legacy[0], "frontend-codex")
        own = write_skill(self.legacy[0], "my-skill")
        self.run_install()
        self.assertFalse(old.parent.exists())
        self.assertTrue(own.is_file())

    def test_without_npx_nothing_is_removed(self):
        self.write_lock({"frontend-codex": f"{pull.REPO_OWNER}/{pull.REPO_NAME}"})
        old = write_skill(self.legacy[0], "frontend-codex")
        self.npx.return_value = None
        self.run_install()
        self.remove.assert_not_called()
        self.assertTrue(old.is_file())


class LockPathTests(unittest.TestCase):
    def test_lock_follows_xdg_state_home_like_the_cli(self):
        with patch.dict(pull.os.environ, {"XDG_STATE_HOME": "/state"}):
            self.assertEqual(pull.skills_lock_path(), Path("/state/skills/.skill-lock.json"))
        with patch.dict(pull.os.environ, {}, clear=True), patch.object(Path, "home", return_value=Path("/h")):
            self.assertEqual(pull.skills_lock_path(), Path("/h/.agents/.skill-lock.json"))


class ExtraEnvTests(unittest.TestCase):
    def test_extra_env_reaches_the_command(self):
        done = subprocess.CompletedProcess(["npx"], 0, stdout=json.dumps(cli_reply()), stderr="")
        with patch.object(pull, "find_agent_executable", return_value=Path("/fake/bin/npx")), \
                patch.object(pull.subprocess, "run", return_value=done) as run:
            document = pull.read_plugin_json(["npx", "--version"], None, None,
                                             extra_env={"DISABLE_TELEMETRY": "1"})
        self.assertEqual(document, [])
        env = run.call_args.kwargs["env"]
        self.assertEqual(env["DISABLE_TELEMETRY"], "1")
        self.assertTrue(env["PATH"].startswith("/fake/bin"))


if __name__ == "__main__":
    unittest.main()
