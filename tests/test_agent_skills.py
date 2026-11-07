"""Shared agent skill install tests.

Repos, agent skill directories and skills CLI JSON replies are synthetic stand-ins in
temporary directories. npx and the skills CLI are never run.
"""

import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from omadotfile import constants
from omadotfile.constants import REMOVED_SKILLS, RETIRED_SKILLS
from omadotfile.context import RepoRef
from omadotfile.core import proc
from omadotfile.core.proc import Runner
from omadotfile.features import skills
from support import ROOT, TestCase, make_context

THIS_REPO = RepoRef()
REPO_SOURCE = THIS_REPO.skills_source


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


class SourceTests(TestCase):
    def setUp(self):
        self.repo = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_repo_skills_are_installed_from_this_repo_at_the_cloned_ref(self):
        # Given repo skills, a folder without SKILL.md, and a stray file.
        for name in ("secret-guard", "github-cli"):
            write_skill(self.repo / "skills", name)
        (self.repo / "skills" / "notes").mkdir()
        _ = (self.repo / "skills" / "README.md").write_text("not a skill\n", encoding="utf-8")
        # Then only real skills are installed, from GitHub at the cloned branch.
        sources = skills.skill_sources(self.repo, THIS_REPO)
        self.assertEqual(sources[REPO_SOURCE], ("github-cli", "secret-guard"))
        # And the upstream skills come from their own repos.
        for source, names in constants.UPSTREAM_SKILLS.items():
            self.assertEqual(sources[source], names)

    def test_repo_without_skills_installs_only_upstream(self):
        self.assertEqual(skills.skill_sources(self.repo, THIS_REPO), constants.UPSTREAM_SKILLS)

    def test_upstream_replaces_the_retired_vendored_copies(self):
        upstream = {name for names in constants.UPSTREAM_SKILLS.values() for name in names} - {constants.ALL_SKILLS}
        self.assertEqual(upstream, {"find-skills", "web-design-guidelines", "frontend-design",
                                    "skill-creator", "ui-ux-pro-max", "herdr"})
        self.assertEqual(constants.RETIRED_SKILLS, {"frontend-claude": "frontend-design"})
        for name in (*upstream, "frontend-claude"):
            self.assertFalse((ROOT / "skills" / name).exists(), name)

    def test_every_ccfa_skill_is_installed(self):
        self.assertEqual(constants.UPSTREAM_SKILLS["mikubaka88/CCFA-Skills"], (constants.ALL_SKILLS,))
        command = skills.add_command("mikubaka88/CCFA-Skills", (constants.ALL_SKILLS,))
        self.assertEqual(command[command.index("-s") + 1:command.index("-s") + 3], ["*", "-y"])

    def test_add_command_can_also_link_into_claude_code(self):
        command = skills.add_command("o/r", ("a", "b"), ("universal", "claude-code"))
        self.assertEqual(command[command.index("-a"):command.index("-s") + 3],
                         ["-a", "universal", "claude-code", "-s", "a", "b"])

    def test_add_command_installs_globally_into_the_shared_dir_only(self):
        command = skills.add_command("vercel-labs/skills", ("find-skills",))
        self.assertEqual(command, [
            "npx", "-y", f"skills@{constants.SKILLS_CLI_VERSION}", "add", "vercel-labs/skills",
            "-g", "-a", "universal", "-s", "find-skills", "-y", "--json",
        ])


class InstalledNamesTests(TestCase):
    def test_only_installed_entries_count(self):
        reply = cli_reply(installed=("skill-creator",), skipped=("frontend-design",))
        self.assertEqual(skills.installed_skill_names(reply), {"skill-creator"})

    def test_unexpected_replies_install_nothing(self):
        for reply in (None, {}, "installed", [None, {"status": "installed"}, {"name": 1, "status": "installed"}]):
            self.assertEqual(skills.installed_skill_names(reply), set(), reply)


class AgentSkillsHarness(TestCase):
    """Fake npx, CLI replies and lock file; holds no tests itself."""

    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.repo = self.tmp / "repo"
        write_skill(self.repo / "skills", "github-cli")
        self.legacy = [self.tmp / "opencode" / "skills", self.tmp / "codex" / "skills"]
        self.ctx = make_context(self.tmp / "home", repo=self.repo)
        # Runner methods are patched on the class: ctx.runner calls them without self.
        self.npx = self.enterContext(patch.object(Runner, "which", return_value=Path("/fake/bin/npx")))
        self.replies: dict[str, object] = {}
        self.cli = self.enterContext(patch.object(Runner, "json", side_effect=self.reply))
        self.lock = self.tmp / "state" / ".skill-lock.json"
        self.enterContext(patch.object(skills, "lock_path", return_value=self.lock))
        self.remove = self.enterContext(patch.object(Runner, "ok", return_value=True))
        # No source commit is known unless a test sets one, so every source installs.
        self.commits: dict[str, str] = {}
        self.enterContext(patch.object(skills, "remote_commits", side_effect=lambda ctx, sources: {
            source: commit for source, commit in self.commits.items() if source in sources}))
        self.shared = self.ctx.shared_skills_dir

    def write_lock(self, sources: dict[str, str]) -> None:
        self.lock.parent.mkdir(parents=True, exist_ok=True)
        skills = {name: {"source": source, "sourceType": "github"} for name, source in sources.items()}
        _ = self.lock.write_text(json.dumps({"version": 3, "skills": skills}), encoding="utf-8")

    def reply(self, command, *args, **kwargs):
        return self.replies.get(command[4])

    def run_install(self) -> str:
        with contextlib.redirect_stdout(io.StringIO()) as out, \
                contextlib.redirect_stderr(io.StringIO()) as err:
            skills.ensure_skills(self.ctx, self.legacy)
        return out.getvalue() + err.getvalue()


class EnsureAgentSkillsTests(AgentSkillsHarness):
    def test_each_source_runs_with_telemetry_off(self):
        self.run_install()
        sources = [call.args[0][4] for call in self.cli.call_args_list]
        self.assertEqual(sources, [*constants.UPSTREAM_SKILLS, REPO_SOURCE])
        for call in self.cli.call_args_list:
            self.assertEqual(call.args[1], {"DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1"})

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

    def test_whole_repo_source_reports_what_it_installed(self):
        self.replies = {"mikubaka88/CCFA-Skills": cli_reply(installed=("ccf-common", "ccf-paper-writer"))}
        output = self.run_install()
        self.assertIn("ccf-common, ccf-paper-writer (mikubaka88/CCFA-Skills)", output)
        self.assertNotIn("Not installed from mikubaka88/CCFA-Skills", output)

    def test_whole_repo_source_that_installs_nothing_warns(self):
        output = self.run_install()
        self.assertIn("Nothing installed from mikubaka88/CCFA-Skills", output)

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
        self.assertIn("         skills skipped: npx not found (install Node.js)\n", output)


class ClaudeCodeSkillTests(AgentSkillsHarness):
    """Claude Code does not read ~/.agents/skills; the CLI links skills into its own dir."""

    def run_with_claude(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            skills.ensure_skills(self.ctx, self.legacy, self.tmp / "claude")

    def installs(self) -> list[tuple[str, tuple[str, ...], tuple[str, ...]]]:
        result = []
        for call in self.cli.call_args_list:
            command = call.args[0]
            agents = tuple(command[command.index("-a") + 1:command.index("-s")])
            names = tuple(command[command.index("-s") + 1:command.index("-y", command.index("-s"))])
            result.append((command[4], names, agents))
        return result

    def test_claude_code_gets_every_skill_but_skill_creator_and_find_skills(self):
        self.run_with_claude()
        both, shared = ("universal", "claude-code"), ("universal",)
        self.assertEqual(self.installs(), [
            ("vercel-labs/skills", ("find-skills",), shared),
            ("vercel-labs/agent-skills", ("web-design-guidelines",), both),
            ("anthropics/skills", ("frontend-design",), both),
            ("anthropics/skills", ("skill-creator",), shared),
            ("nextlevelbuilder/ui-ux-pro-max-skill", ("ui-ux-pro-max",), both),
            ("mikubaka88/CCFA-Skills", (constants.ALL_SKILLS,), both),
            ("herdrdev/herdr", ("herdr",), both),
            (REPO_SOURCE, ("github-cli",), both),
        ])

    def test_claude_config_dir_is_passed_to_the_cli(self):
        self.run_with_claude()
        for call in self.cli.call_args_list:
            self.assertEqual(call.args[1]["CLAUDE_CONFIG_DIR"], str(self.tmp / "claude"))

    def test_without_claude_code_nothing_links_into_it(self):
        self.run_install()
        for source, names, agents in self.installs():
            self.assertEqual(agents, ("universal",), source)
        for call in self.cli.call_args_list:
            self.assertNotIn("CLAUDE_CONFIG_DIR", call.args[1])


class RemovedSkillTests(AgentSkillsHarness):
    """Skills dropped from this repo are uninstalled from ~/.agents/skills."""

    def test_frontend_codex_is_no_longer_shipped(self):
        self.assertIn("frontend-codex", constants.REMOVED_SKILLS)
        self.assertFalse((ROOT / "skills" / "frontend-codex").exists())
        self.assertNotIn("frontend-codex", skills.skill_sources(ROOT, THIS_REPO).get(REPO_SOURCE, ()))

    def test_skill_installed_from_this_repo_is_removed_with_the_cli(self):
        self.write_lock({"frontend-codex": THIS_REPO.slug, "ccf-common": "someone/else"})
        output = self.run_install()
        command = self.remove.call_args.args[0]
        self.assertEqual(command, ["npx", "-y", f"skills@{constants.SKILLS_CLI_VERSION}", "remove",
                                   "frontend-codex", "-g", "-y"])
        self.assertEqual(self.remove.call_args.args[1], skills.SKILLS_CLI_ENV)
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
        self.write_lock({"frontend-codex": THIS_REPO.slug})
        old = write_skill(self.legacy[0], "frontend-codex")
        self.npx.return_value = None
        self.run_install()
        self.remove.assert_not_called()
        self.assertTrue(old.is_file())


class PureSkillPlanTests(TestCase):
    def test_record_keeps_the_commit_of_each_complete_run_only(self):
        results = [skills.InstallResult("a", frozenset({"x"}), "1" * 40),
                   skills.InstallResult("b", frozenset(), None),
                   skills.InstallResult("c", frozenset({"y", "z"}), "2" * 40)]
        self.assertEqual(skills.recorded_commits(results), {"a": "1" * 40, "c": "2" * 40})
        self.assertEqual(skills.recorded_commits([]), {})

    def test_legacy_copy_names_add_retired_and_removed_skills(self):
        retired, replacement = next(iter(RETIRED_SKILLS.items()))
        names = skills.legacy_copy_names({replacement, "mine"})
        self.assertEqual(names, sorted(names))
        self.assertTrue({replacement, "mine", retired, *REMOVED_SKILLS} <= set(names))
        self.assertNotIn(retired, skills.legacy_copy_names(set()))


class SkipUnchangedSourceTests(AgentSkillsHarness):
    """A source whose commit has not moved since its last full install is not reinstalled."""

    SOURCE = "vercel-labs/skills"
    NAMES = ("find-skills",)
    AGENTS = ("universal",)

    def setUp(self):
        super().setUp()
        self.claude = self.tmp / "claude"

    def record(self, source=SOURCE, names=NAMES, agents=AGENTS, commit="a" * 40) -> None:
        path = skills.commits_path(self.ctx)
        path.parent.mkdir(parents=True, exist_ok=True)
        recorded = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        recorded[skills.install_key(source, names, agents)] = commit
        _ = path.write_text(json.dumps(recorded), encoding="utf-8")

    def installed_on_disk(self, *names: str) -> None:
        for name in names:
            write_skill(self.shared, name)

    def ran(self) -> list[str]:
        return [call.args[0][4] for call in self.cli.call_args_list]

    def run_with_claude(self) -> str:
        with contextlib.redirect_stdout(io.StringIO()) as out, \
                contextlib.redirect_stderr(io.StringIO()) as err:
            skills.ensure_skills(self.ctx, self.legacy, self.claude)
        return out.getvalue() + err.getvalue()

    def test_unchanged_source_with_its_skills_on_disk_is_skipped(self):
        self.commits = {self.SOURCE: "a" * 40}
        self.record()
        self.installed_on_disk("find-skills")
        old = write_skill(self.legacy[0], "find-skills")
        output = self.run_install()
        self.assertNotIn(self.SOURCE, self.ran())
        self.assertIn("find-skills (vercel-labs/skills, unchanged)", output)
        # The skipped skill still counts as installed, so a leftover per-agent copy goes.
        self.assertFalse(old.exists())

    def test_full_install_records_the_commit(self):
        self.commits = {self.SOURCE: "b" * 40}
        self.replies = {self.SOURCE: cli_reply(installed=self.NAMES)}
        self.run_install()
        recorded = json.loads(skills.commits_path(self.ctx).read_text(encoding="utf-8"))
        self.assertEqual(recorded[skills.install_key(self.SOURCE, self.NAMES, self.AGENTS)], "b" * 40)

    def test_new_commit_reinstalls(self):
        self.commits = {self.SOURCE: "b" * 40}
        self.record(commit="a" * 40)
        self.installed_on_disk("find-skills")
        self.run_install()
        self.assertIn(self.SOURCE, self.ran())

    def test_missing_skill_dir_reinstalls(self):
        self.commits = {self.SOURCE: "a" * 40}
        self.record()
        self.run_install()
        self.assertIn(self.SOURCE, self.ran())

    def test_unknown_commit_reinstalls_and_records_nothing(self):
        self.record()
        self.installed_on_disk("find-skills")
        self.replies = {self.SOURCE: cli_reply(installed=self.NAMES)}
        self.run_install()
        self.assertIn(self.SOURCE, self.ran())
        recorded = json.loads(skills.commits_path(self.ctx).read_text(encoding="utf-8"))
        self.assertNotIn(skills.install_key(self.SOURCE, self.NAMES, self.AGENTS), recorded)

    def test_incomplete_install_forgets_the_commit(self):
        self.commits = {"anthropics/skills": "c" * 40}
        names = ("frontend-design", "skill-creator")
        self.replies = {"anthropics/skills": cli_reply(installed=("skill-creator",), skipped=("frontend-design",))}
        self.run_install()
        recorded = json.loads(skills.commits_path(self.ctx).read_text(encoding="utf-8"))
        self.assertNotIn(skills.install_key("anthropics/skills", names, self.AGENTS), recorded)

    def test_unreadable_record_reinstalls(self):
        self.commits = {self.SOURCE: "a" * 40}
        self.installed_on_disk("find-skills")
        skills.commits_path(self.ctx).parent.mkdir(parents=True, exist_ok=True)
        _ = skills.commits_path(self.ctx).write_text("{not json", encoding="utf-8")
        self.run_install()
        self.assertIn(self.SOURCE, self.ran())

    def test_whole_repo_source_is_skipped_by_its_lock_entries(self):
        source = "mikubaka88/CCFA-Skills"
        self.commits = {source: "d" * 40}
        self.record(source, (constants.ALL_SKILLS,), commit="d" * 40)
        self.write_lock({"ccf-common": "mikubaka88/ccfa-skills", "ccf-paper-writer": source, "other": "x/y"})
        self.installed_on_disk("ccf-common", "ccf-paper-writer")
        output = self.run_install()
        self.assertNotIn(source, self.ran())
        self.assertIn("ccf-common, ccf-paper-writer (mikubaka88/CCFA-Skills, unchanged)", output)

    def test_whole_repo_source_without_lock_entries_reinstalls(self):
        source = "mikubaka88/CCFA-Skills"
        self.commits = {source: "d" * 40}
        self.record(source, (constants.ALL_SKILLS,), commit="d" * 40)
        self.run_install()
        self.assertIn(source, self.ran())

    def test_this_repo_is_matched_in_the_lock_without_its_ref(self):
        self.commits = {REPO_SOURCE: "e" * 40}
        self.record(REPO_SOURCE, ("github-cli",), commit="e" * 40)
        self.installed_on_disk("github-cli")
        self.run_install()
        self.assertNotIn(REPO_SOURCE, self.ran())

    def test_missing_claude_code_link_reinstalls(self):
        both = ("universal", "claude-code")
        self.commits = {"herdrdev/herdr": "f" * 40}
        self.record("herdrdev/herdr", ("herdr",), both, commit="f" * 40)
        self.installed_on_disk("herdr")
        self.run_with_claude()
        self.assertIn("herdrdev/herdr", self.ran())

    def test_present_claude_code_link_is_skipped(self):
        both = ("universal", "claude-code")
        self.commits = {"herdrdev/herdr": "f" * 40}
        self.record("herdrdev/herdr", ("herdr",), both, commit="f" * 40)
        self.installed_on_disk("herdr")
        (self.claude / "skills").mkdir(parents=True)
        (self.claude / "skills" / "herdr").symlink_to(self.shared / "herdr", target_is_directory=True)
        self.run_with_claude()
        self.assertNotIn("herdrdev/herdr", self.ran())

    def test_turning_on_claude_code_reinstalls(self):
        # Recorded for the shared dir only; now Claude Code is found and needs the link.
        self.commits = {"herdrdev/herdr": "f" * 40}
        self.record("herdrdev/herdr", ("herdr",), self.AGENTS, commit="f" * 40)
        self.installed_on_disk("herdr")
        self.run_with_claude()
        self.assertIn("herdrdev/herdr", self.ran())

    def test_new_cli_version_reinstalls(self):
        key = skills.install_key(self.SOURCE, self.NAMES, self.AGENTS)
        with patch.object(skills, "SKILLS_CLI_VERSION", "0.0.0-other"):
            self.assertNotEqual(skills.install_key(self.SOURCE, self.NAMES, self.AGENTS), key)

    def test_record_sits_next_to_the_cli_lock(self):
        self.assertEqual(skills.commits_path(self.ctx).parent, self.lock.parent)


class RemoteCommitTests(TestCase):
    """`git ls-remote` replies here are synthetic; no network is used."""

    def ls_remote(self, stdout: str = "", returncode: int = 0, error: Exception | None = None):
        done = subprocess.CompletedProcess(["git"], returncode, stdout=stdout, stderr="")
        return patch.object(skills.subprocess, "run", side_effect=error, return_value=done)

    def setUp(self):
        self.ctx = make_context(Path("/h"))

    def test_default_branch_is_read_from_head(self):
        with self.ls_remote(f"{'1' * 40}\tHEAD\n") as run:
            self.assertEqual(skills.ls_remote_commit(self.ctx, "o/r"), "1" * 40)
        command = run.call_args.args[0]
        self.assertEqual(command[-2:], ["https://github.com/o/r.git", "HEAD"])
        self.assertEqual(run.call_args.kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")

    def test_ref_prefers_the_branch_then_the_peeled_tag(self):
        reply = f"{'2' * 40}\trefs/tags/v1\n{'3' * 40}\trefs/tags/v1^{{}}\n{'4' * 40}\trefs/heads/v1\n"
        with self.ls_remote(reply) as run:
            self.assertEqual(skills.ls_remote_commit(self.ctx, "o/r#v1"), "4" * 40)
        self.assertEqual(run.call_args.args[0][-2:], ["https://github.com/o/r.git", "v1"])
        with self.ls_remote(reply.rsplit("\n", 2)[0] + "\n"):
            self.assertEqual(skills.ls_remote_commit(self.ctx, "o/r#v1"), "3" * 40)

    def test_failures_give_no_commit(self):
        for context in (self.ls_remote(returncode=2), self.ls_remote("garbage\n"),
                        self.ls_remote(error=OSError("no git")),
                        self.ls_remote(error=subprocess.TimeoutExpired(["git"], 1))):
            with context:
                self.assertIsNone(skills.ls_remote_commit(self.ctx, "o/r"))

    def test_sources_are_looked_up_together(self):
        with patch.object(skills, "ls_remote_commit",
                          side_effect=lambda ctx, s: None if s == "x/y" else s[0] * 40):
            self.assertEqual(skills.remote_commits(self.ctx, {"a/b", "x/y"}), {"a/b": "a" * 40})


class LockPathTests(TestCase):
    def test_lock_follows_xdg_state_home_like_the_cli(self):
        state = make_context(Path("/h"), env={"XDG_STATE_HOME": "/state"})
        self.assertEqual(skills.lock_path(state), Path("/state/skills/.skill-lock.json"))
        self.assertEqual(skills.lock_path(make_context(Path("/h"))), Path("/h/.agents/.skill-lock.json"))


class ExtraEnvTests(TestCase):
    def test_extra_env_reaches_the_command(self):
        done = subprocess.CompletedProcess(["npx"], 0, stdout=json.dumps(cli_reply()), stderr="")
        with patch.object(proc, "find_executable", return_value=Path("/fake/bin/npx")), \
                patch.object(proc.subprocess, "run", return_value=done) as run:
            document = Runner({}, Path("/h")).json(["npx", "--version"], {"DISABLE_TELEMETRY": "1"})
        self.assertEqual(document, [])
        env = run.call_args.kwargs["env"]
        self.assertEqual(env["DISABLE_TELEMETRY"], "1")
        self.assertTrue(env["PATH"].startswith("/fake/bin"))


if __name__ == "__main__":
    unittest.main()
