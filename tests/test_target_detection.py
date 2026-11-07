"""Synthetic PATHs and temporary HOMEs only; no real agent or user directory is touched."""

import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from omadotfile import cli
from omadotfile.agents import claude, omo_native, tokscale
from omadotfile.agents.base import AGENT_CLASSES, Agent, agent
from omadotfile.constants import LEGACY_OMO_CONFIG_NAMES, LEGACY_OPENAGENT_CONFIG_NAMES
from omadotfile.core import proc
from omadotfile.features import skills, wakatime
from support import ROOT, TestCase


def make_executable(path: Path) -> None:
    """Create a stand-in agent CLI that `which` will accept."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(0o755)


# Captured before patching: proc.shutil is the shared module, so a helper calling
# shutil.which while the patch is active would recurse into itself.
REAL_WHICH = shutil.which


def which_only_via_extra_path(name: str, path: str | None = None):
    """Answer like shutil.which for a machine whose PATH lists no agent at all."""
    if path is None:
        return None
    return REAL_WHICH(name, path=path)


class AgentDetectionTests(TestCase):
    def test_path_executable_is_detected(self) -> None:
        # Given only codex on PATH.
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(proc.shutil, "which",
                             lambda name, path=None: "/usr/bin/codex" if name == "codex" else None):
            # When each agent is resolved.
            codex = proc.find_executable("codex", Path(tmp))
            opencode = proc.find_executable("opencode", Path(tmp))
        # Then only codex resolves.
        self.assertEqual(codex, Path("/usr/bin/codex"))
        self.assertIsNone(opencode)

    def test_empty_command_name_never_resolves(self) -> None:
        # Given a target that ships no CLI, such as Tokscale.
        self.assertIsNone(proc.find_executable("", Path.home()))
        self.assertIsNone(proc.find_executable(None, Path.home()))

    def test_home_bin_directories_are_searched_when_path_omits_them(self) -> None:
        # Given agents installed in per-user bin directories that PATH does not list.
        for relative in (".opencode/bin/opencode",
                         ".bun/bin/omp",
                         ".local/bin/claude",
                         ".nvm/versions/node/v24.11.1/bin/codex"):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp)
                make_executable(home / relative)
                command = Path(relative).name
                with patch.object(proc.shutil, "which", which_only_via_extra_path):
                    # When the agent is resolved.
                    found = proc.find_executable(command, home)
                # Then the known install location is searched too.
                self.assertEqual(found, home / relative)

    def test_newest_nvm_node_wins(self) -> None:
        # Given the same CLI under several nvm versions; string order would pick v20 and
        # put v9 after v10.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            for version in ("v9.11.2", "v10.0.0", "v20.13.1", "v24.11.1"):
                make_executable(home / f".nvm/versions/node/{version}/bin/codex")
            with patch.object(proc.shutil, "which", which_only_via_extra_path):
                found = proc.find_executable("codex", home)
                nvm_dirs = [Path(d).parent.name for d in proc.extra_bin_search_path(home).split(os.pathsep)
                            if ".nvm" in d]
        # Then the newest install is used, as a fresh nvm shell would.
        self.assertEqual(found, home / ".nvm/versions/node/v24.11.1/bin/codex")
        self.assertEqual(nvm_dirs, ["v24.11.1", "v20.13.1", "v10.0.0", "v9.11.2"])

    def test_detect_targets_reads_every_agent(self) -> None:
        # Given a machine with only opencode and omp installed.
        installed = {"opencode", "omp"}
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(proc.shutil, "which",
                             lambda name, path=None: f"/usr/bin/{name}" if name in installed else None):
            found = cli.detect_agents({}, Path(tmp))
        # Then exactly those targets are enabled.
        self.assertEqual(found, frozenset({"opencode", "omp"}))

    def test_tokscale_follows_its_config_directory(self) -> None:
        # Given Tokscale, which ships no CLI on PATH.
        with tempfile.TemporaryDirectory() as tmp:
            present = Path(tmp) / "present"
            present.mkdir()
            for config_dir, expected in ((present, True), (Path(tmp) / "absent", False)):
                with self.subTest(config_dir=config_dir.name), \
                        patch.object(proc.shutil, "which", lambda name, path=None: None):
                    # When targets are detected.
                    found = cli.detect_agents({"TOKSCALE_CONFIG_DIR": str(config_dir)}, Path(tmp))
                # Then its configuration directory decides.
                self.assertEqual("tokscale" in found, expected)

    def test_force_enables_every_target_without_any_agent(self) -> None:
        # Given a machine with nothing installed.
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(proc.shutil, "which", lambda name, path=None: None):
            # When detection is forced.
            found = cli.detect_agents({}, Path(tmp), force=True)
        # Then every known target is enabled.
        self.assertEqual(found, frozenset(cli.AGENTS))

    def test_agents_are_registered_by_their_decorator_in_report_order(self) -> None:
        self.assertEqual(list(cli.AGENTS), ["opencode", "omo", "omp", "codex", "claude", "tokscale"])
        self.assertEqual(set(cli.AGENTS), set(AGENT_CLASSES))
        codex = cli.AGENTS["codex"]
        self.assertIsInstance(codex, AGENT_CLASSES["codex"])
        self.assertEqual((codex.key, codex.label, codex.executable), ("codex", "Codex", "codex"))
        self.assertIsNone(cli.AGENTS["tokscale"].executable)

    def test_agent_decorator_returns_the_class_and_refuses_a_second_key(self) -> None:
        before = dict(AGENT_CLASSES)
        try:
            @agent("test-agent", label="Test Agent", executable=None)
            class TestAgent(Agent):
                pass

            self.assertIs(AGENT_CLASSES["test-agent"], TestAgent)
            self.assertEqual((TestAgent.key, TestAgent.label, TestAgent.executable),
                             ("test-agent", "Test Agent", None))
            with self.assertRaisesRegex(ValueError, "registered twice"):
                agent("test-agent", label="Again", executable=None)(type("Again", (Agent,), {}))
        finally:
            AGENT_CLASSES.clear()
            AGENT_CLASSES.update(before)

    def test_report_names_detected_and_skipped_targets(self) -> None:
        # Given a machine with Codex but no Claude Code.
        with contextlib.redirect_stdout(io.StringIO()) as out, \
                contextlib.redirect_stderr(io.StringIO()) as err:
            cli.report_agents(frozenset({"codex"}))
        # Then both sides are named and the escape hatch is offered.
        self.assertIn("Codex", out.getvalue())
        self.assertIn("Claude Code", err.getvalue())
        self.assertIn("--all", out.getvalue())

    def test_report_is_quiet_about_skipping_when_everything_is_detected(self) -> None:
        # Given a machine with every agent installed.
        with contextlib.redirect_stdout(io.StringIO()) as out, \
                contextlib.redirect_stderr(io.StringIO()) as err:
            cli.report_agents(frozenset(cli.AGENTS))
        # Then nothing is reported as skipped.
        self.assertEqual(err.getvalue(), "")
        self.assertNotIn("--all", out.getvalue())


# Where each agent's config goes in these tests, named as the legacy getters were.
DIR_ENV = {
    "get_config_dir": "CONFIG_DIR",
    "get_omo_agent_dir": "OMO_CODING_AGENT_DIR",
    "get_codex_dir": "CODEX_DIR",
    "get_claude_config_dir": "CLAUDE_CONFIG_DIR",
    "get_omp_agent_dir": "OMP_AGENT_DIR",
    "get_tokscale_config_dir": "TOKSCALE_CONFIG_DIR",
}
GATEWAY = {"CODEX_BASE_URL": "https://example.invalid/v1"}


class InstallGatingTests(TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.env = {name: str(self.tmp / getter) for getter, name in DIR_ENV.items()}
        self.env["NO_BACKUP"] = "1"
        self.wakatime = self.enterContext(patch.object(wakatime, "ensure_plugins"))
        # npm and the omo-herdr-dag installer would hit the fake checkout below.
        self.herdr_dag = self.enterContext(patch.object(omo_native, "ensure_herdr_dag"))
        # npx and the skills CLI would hit the same fake checkout.
        self.agent_skills = self.enterContext(patch.object(skills, "ensure_skills"))
        # git config must not reach the real ~/.gitconfig.
        self.git_hook = self.enterContext(patch.object(claude, "ensure_commit_msg_hook"))
        # Never reach the developer's real ~/.wakatime.cfg.
        self.wakatime_config = self.enterContext(patch.object(wakatime, "ensure_config"))
        self.tokscale = self.enterContext(patch.object(tokscale, "install_model_aliases"))

        # A checkout with only the files these tests need.
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        for name in ("opencode.jsonc", "omo.jsonc", "omp_config.yml", "omp_models.yaml",
                     "_AGENTS.md", "tui.json", "codex-gotify-notify.py",
                     "omp-gotify-notify.js", "omp-wakatime-sync.js"):
            _ = shutil.copy2(ROOT / name, self.repo / name)
        _ = shutil.copytree(ROOT / "skills", self.repo / "skills")

    def main(self, argv, env=None):
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            cli.main(argv, repo=self.repo, env={**self.env, **(env or {})}, home=self.home)

    def run_main(self, argv=None, env=None, **detected):
        """Run the installer with a fixed detection result."""
        found = frozenset(name for name in cli.AGENTS if detected.get(name, False))
        with patch.object(cli, "detect_agents", return_value=found):
            self.main(argv if argv is not None else [], env)
        return found

    def target_dir(self, name: str) -> Path:
        if name == "get_omo_dir":
            return self.home / ".omo"
        return self.tmp / name

    def test_only_detected_targets_are_written(self) -> None:
        # Given a machine with OpenCode but nothing else.
        self.run_main(opencode=True, env=GATEWAY)
        # Then OpenCode and its OMO config are installed.
        self.assertTrue((self.target_dir("get_config_dir") / "opencode.jsonc").is_file())
        self.assertTrue((self.target_dir("get_omo_dir") / "omo.jsonc").is_file())
        # And no directory is created for an agent that is not installed.
        for name in ("get_codex_dir", "get_omp_agent_dir", "get_claude_config_dir"):
            self.assertFalse(self.target_dir(name).exists(), name)
        self.wakatime.assert_not_called()
        self.tokscale.assert_not_called()

    def test_omo_only_machine_gets_unified_and_native_config(self) -> None:
        # Given a machine with OMO Native but no OpenCode.
        self.run_main(omo=True, env=GATEWAY)
        # Then the shared OMO config and the native agent files are installed.
        self.assertTrue((self.target_dir("get_omo_dir") / "omo.jsonc").is_file())
        agent_dir = self.target_dir("get_omo_agent_dir")
        for name in ("AGENTS.md", "models.json", "settings.json"):
            self.assertTrue((agent_dir / name).is_file(), name)
        self.assertEqual(self.herdr_dag.call_args.args[1], agent_dir)
        # And OpenCode itself is left alone.
        self.assertFalse(self.target_dir("get_config_dir").exists())

    def test_opencode_only_machine_does_not_create_native_agent_dir(self) -> None:
        self.run_main(opencode=True, env=GATEWAY)
        self.assertTrue((self.target_dir("get_omo_dir") / "omo.jsonc").is_file())
        self.assertFalse(self.target_dir("get_omo_agent_dir").exists())
        self.herdr_dag.assert_not_called()

    def test_codex_only_machine_leaves_the_other_agents_alone(self) -> None:
        # Given a machine with Codex but nothing else.
        self.run_main(codex=True, env=GATEWAY)
        # Then Codex is configured.
        self.assertTrue((self.target_dir("get_codex_dir") / "config.toml").is_file())
        self.assertTrue((self.target_dir("get_codex_dir") / "AGENTS.md").is_file())
        # And the OpenCode, OMO, and oh-my-pi directories are never created.
        for name in ("get_config_dir", "get_omo_dir", "get_omp_agent_dir"):
            self.assertFalse(self.target_dir(name).exists(), name)

    def test_omp_only_machine_gets_both_extensions(self) -> None:
        # Given a machine with oh-my-pi but nothing else.
        self.run_main(omp=True, env=GATEWAY)
        # Then the Gotify notifier and the WakaTime sync trigger are both installed.
        extensions = self.target_dir("get_omp_agent_dir") / "extensions"
        for name in ("omp-gotify-notify.js", "omp-wakatime-sync.js"):
            self.assertEqual((extensions / name).read_bytes(), (ROOT / name).read_bytes(), name)

    def test_omp_gets_user_level_instructions(self) -> None:
        # Given an OMP agent dir with locally edited instructions. OMP ignores
        # ~/.config/opencode/AGENTS.md unless opencode is in enabledProviders.
        agent_dir = self.target_dir("get_omp_agent_dir")
        agent_dir.mkdir(parents=True)
        _ = (agent_dir / "AGENTS.md").write_text("local rules\n", encoding="utf-8")
        self.run_main(omp=True, env={**GATEWAY, "NO_BACKUP": "0"})
        # Then OMP's native user-level AGENTS.md holds the shared rules.
        self.assertEqual((agent_dir / "AGENTS.md").read_bytes(), (ROOT / "_AGENTS.md").read_bytes())
        # And the edited copy is kept as a backup, like other user-editable config.
        backups = list(agent_dir.glob("AGENTS.md.bak-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), "local rules\n")

    def test_repo_skills_are_not_copied_into_agent_dirs(self) -> None:
        # Given OMP skills: one of the user's own and autolearn output.
        agent_dir = self.target_dir("get_omp_agent_dir")
        own = agent_dir / "skills" / "my-skill" / "SKILL.md"
        learned = agent_dir / "managed-skills" / "learned" / "SKILL.md"
        for path in (own, learned):
            path.parent.mkdir(parents=True, exist_ok=True)
            _ = path.write_text("kept\n", encoding="utf-8")
        self.run_main(omp=True, opencode=True, codex=True, env=GATEWAY)
        # Then no agent gets its own copy of the repo skills; they go to ~/.agents/skills.
        for name in ("get_config_dir", "get_codex_dir", "get_omp_agent_dir"):
            for skill in (ROOT / "skills").iterdir():
                self.assertFalse((self.target_dir(name) / "skills" / skill.name).exists(), skill.name)
        # And the user's own skills are left alone.
        self.assertEqual(own.read_text(encoding="utf-8"), "kept\n")
        self.assertEqual(learned.read_text(encoding="utf-8"), "kept\n")

    def test_shared_skills_clean_only_detected_agent_dirs(self) -> None:
        self.run_main(omp=True, codex=True, env=GATEWAY)
        legacy = self.agent_skills.call_args.args[1]
        self.assertEqual(legacy, [self.target_dir("get_codex_dir") / "skills",
                                  self.target_dir("get_omp_agent_dir") / "skills"])
        # And Claude Code, not detected, gets no links.
        self.assertIsNone(self.agent_skills.call_args.args[2])

    def test_claude_only_machine_gets_skills_linked_into_claude_code(self) -> None:
        self.run_main(claude=True, env=GATEWAY)
        self.assertEqual(self.agent_skills.call_args.args[1:],
                         ([], self.target_dir("get_claude_config_dir")))

    def test_no_skill_reader_means_no_skills(self) -> None:
        self.run_main(env=GATEWAY)
        self.agent_skills.assert_not_called()

    def test_reinstall_backs_up_changed_config_but_not_plugin_code(self) -> None:
        # Given stale copies of shared config and of repo-managed plugin code.
        codex_dir = self.target_dir("get_codex_dir")
        extensions = self.target_dir("get_omp_agent_dir") / "extensions"
        extensions.mkdir(parents=True)
        codex_dir.mkdir(parents=True)
        stale = {
            codex_dir / "AGENTS.md": "local rules\n",
            codex_dir / "codex-gotify-notify.py": "old notifier\n",
            extensions / "omp-gotify-notify.js": "old extension\n",
            extensions / "omp-wakatime-sync.js": "old extension\n",
        }
        for path, content in stale.items():
            _ = path.write_text(content, encoding="utf-8")
        # When the installer runs with backups enabled.
        self.run_main(omp=True, codex=True, env={**GATEWAY, "NO_BACKUP": "0"})
        # Then every file is updated from the repo.
        self.assertEqual((codex_dir / "AGENTS.md").read_bytes(), (ROOT / "_AGENTS.md").read_bytes())
        for path in list(stale)[1:]:
            self.assertEqual(path.read_bytes(), (ROOT / path.name).read_bytes(), path.name)
        # And only the user-editable config keeps a backup.
        self.assertEqual(len(list(codex_dir.glob("AGENTS.md.bak-*"))), 1)
        self.assertEqual(list(codex_dir.glob("codex-gotify-notify.py.bak-*")), [])
        self.assertEqual(list(extensions.glob("*.bak-*")), [])

    def test_claude_code_commits_carry_no_attribution(self) -> None:
        self.run_main(claude=True)
        settings = self.target_dir("get_claude_config_dir") / "settings.json"
        self.assertEqual(json.loads(settings.read_text(encoding="utf-8"))["attribution"],
                         {"commit": "", "pr": ""})
        self.git_hook.assert_called_once()

    def test_no_claude_code_means_no_git_hook(self) -> None:
        self.run_main(codex=True)
        self.git_hook.assert_not_called()

    def test_claude_instructions_preserve_existing_user_memory(self) -> None:
        # Existing personal instructions must remain separate from the shared rules.
        claude_dir = self.target_dir("get_claude_config_dir")
        rules_dir = claude_dir / "rules"
        rules_dir.mkdir(parents=True)
        personal = claude_dir / "CLAUDE.md"
        _ = personal.write_text("Personal instructions\n", encoding="utf-8")
        managed = rules_dir / "oma-dotfile.md"
        _ = managed.write_text("Old shared instructions\n", encoding="utf-8")

        self.run_main(claude=True, env={"NO_BACKUP": "0"})
        self.assertEqual(managed.read_text(encoding="utf-8"),
                         (ROOT / "_AGENTS.md").read_text(encoding="utf-8"))
        self.assertEqual(personal.read_text(encoding="utf-8"),
                         "Personal instructions\n")
        backups = list(rules_dir.glob("oma-dotfile.md.bak-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"),
                         "Old shared instructions\n")

        self.run_main(claude=True, env={"NO_BACKUP": "0"})
        self.assertEqual(list(rules_dir.glob("oma-dotfile.md.bak-*")), backups)

    def test_wakatime_step_follows_either_agent(self) -> None:
        # Given each combination of the two agents that carry a WakaTime plugin.
        for detected, expected_calls in (({"codex": True}, 1), ({"claude": True}, 1),
                                         ({"codex": True, "claude": True}, 1), ({}, 0)):
            with self.subTest(detected=sorted(detected)):
                self.wakatime.reset_mock()
                self.run_main(**detected, env=GATEWAY)
                # Then the step runs whenever at least one of them is installed.
                self.assertEqual(self.wakatime.call_count, expected_calls)

    def test_wakatime_config_follows_any_tracked_agent(self) -> None:
        # Given each agent alone; OMO Native and Tokscale have no WakaTime integration.
        for name in cli.AGENTS:
            with self.subTest(target=name):
                self.wakatime_config.reset_mock()
                self.wakatime.reset_mock()
                self.run_main(**{name: True}, env=GATEWAY)
                # Then the cfg is rendered for every agent that WakaTime tracks.
                tracked = name in ("opencode", "omp", "codex", "claude")
                self.assertEqual(self.wakatime_config.call_count, int(tracked))
                # And plugins are still installed only for Codex and Claude Code.
                self.assertEqual(self.wakatime.call_count, int(name in ("codex", "claude")))

    def test_nothing_detected_writes_nothing(self) -> None:
        # Given a machine with no agent at all.
        self.run_main()
        # Then the run completes without creating a single target directory.
        for name in ("get_config_dir", "get_omo_dir", "get_codex_dir",
                     "get_claude_config_dir", "get_omp_agent_dir"):
            self.assertFalse(self.target_dir(name).exists(), name)

    def test_all_flag_installs_every_target_without_detection(self) -> None:
        # Given nothing installed and no detectable agent.
        with patch.object(proc.shutil, "which", lambda name, path=None: None):
            # When the installer is forced.
            self.main(["--all"], GATEWAY)
        # Then every target directory is written anyway.
        for name in ("get_config_dir", "get_omo_dir", "get_codex_dir", "get_omp_agent_dir"):
            self.assertTrue(self.target_dir(name).is_dir(), name)
        self.wakatime.assert_called_once()
        self.tokscale.assert_called_once()

    def test_install_all_environment_variable_matches_the_flag(self) -> None:
        # Given INSTALL_ALL=1 instead of the flag, as the piped curl install would use.
        with patch.object(proc.shutil, "which", lambda name, path=None: None):
            self.main([], {**GATEWAY, "INSTALL_ALL": "1"})
        # Then every target is installed just as --all does.
        for name in ("get_config_dir", "get_omo_dir", "get_codex_dir", "get_omp_agent_dir"):
            self.assertTrue(self.target_dir(name).is_dir(), name)

    def test_legacy_opencode_files_are_retired_with_opencode(self) -> None:
        # Given legacy configuration left in both OpenCode and OMO directories.
        config_dir = self.target_dir("get_config_dir")
        omo_dir = self.target_dir("get_omo_dir")
        for directory in (config_dir, omo_dir):
            directory.mkdir(parents=True)
        legacy_opencode = config_dir / LEGACY_OPENAGENT_CONFIG_NAMES[0]
        legacy_omo = omo_dir / LEGACY_OMO_CONFIG_NAMES[0]
        for legacy in (legacy_opencode, legacy_omo):
            _ = legacy.write_text("{}\n", encoding="utf-8")
        # When OpenCode is detected.
        self.run_main(opencode=True, env=GATEWAY)
        # Then both legacy files are retired, including the OpenCode one that used to be
        # retired from inside the OMO step.
        self.assertFalse(legacy_opencode.exists())
        self.assertFalse(legacy_omo.exists())


if __name__ == "__main__":
    unittest.main()
