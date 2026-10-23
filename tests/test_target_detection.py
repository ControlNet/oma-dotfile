"""Synthetic PATHs and temporary HOMEs only; no real agent or user directory is touched."""

import contextlib
import importlib.util
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pull_targets", ROOT / "pull.py")
assert SPEC is not None and SPEC.loader is not None
pull = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pull)


def make_executable(path: Path) -> None:
    """Create a stand-in agent CLI that `which` will accept."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(0o755)


# Captured before patching: pull.shutil is the shared module, so a helper calling
# shutil.which while the patch is active would recurse into itself.
REAL_WHICH = shutil.which


def which_only_via_extra_path(name: str, path: str | None = None):
    """Answer like shutil.which for a machine whose PATH lists no agent at all."""
    if path is None:
        return None
    return REAL_WHICH(name, path=path)


class AgentDetectionTests(unittest.TestCase):
    def test_path_executable_is_detected(self) -> None:
        # Given only codex on PATH.
        with patch.object(pull.shutil, "which",
                          lambda name, path=None: "/usr/bin/codex" if name == "codex" else None):
            # When each agent is resolved.
            codex = pull.find_agent_executable("codex")
            opencode = pull.find_agent_executable("opencode")
        # Then only codex resolves.
        self.assertEqual(codex, Path("/usr/bin/codex"))
        self.assertIsNone(opencode)

    def test_empty_command_name_never_resolves(self) -> None:
        # Given a target that ships no CLI, such as Tokscale.
        self.assertIsNone(pull.find_agent_executable(""))

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
                with patch.object(Path, "home", return_value=home), \
                        patch.object(pull.shutil, "which", which_only_via_extra_path):
                    # When the agent is resolved.
                    found = pull.find_agent_executable(command)
                # Then the known install location is searched too.
                self.assertEqual(found, home / relative)

    def test_newest_nvm_node_wins(self) -> None:
        # Given the same CLI under several nvm versions; string order would pick v20 and
        # put v9 after v10.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            for version in ("v9.11.2", "v10.0.0", "v20.13.1", "v24.11.1"):
                make_executable(home / f".nvm/versions/node/{version}/bin/codex")
            with patch.object(Path, "home", return_value=home), \
                    patch.object(pull.shutil, "which", which_only_via_extra_path):
                found = pull.find_agent_executable("codex")
                nvm_dirs = [Path(d).parent.name for d in pull.extra_bin_search_path().split(os.pathsep)
                            if ".nvm" in d]
        # Then the newest install is used, as a fresh nvm shell would.
        self.assertEqual(found, home / ".nvm/versions/node/v24.11.1/bin/codex")
        self.assertEqual(nvm_dirs, ["v24.11.1", "v20.13.1", "v10.0.0", "v9.11.2"])

    def test_detect_targets_reads_every_agent(self) -> None:
        # Given a machine with only opencode and omp installed.
        installed = {"opencode", "omp"}
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(Path, "home", return_value=Path(tmp)), \
                patch.object(pull.shutil, "which",
                             lambda name, path=None: f"/usr/bin/{name}" if name in installed else None):
            targets = pull.detect_targets()
        # Then exactly those targets are enabled.
        self.assertTrue(targets["opencode"])
        self.assertTrue(targets["omp"])
        self.assertFalse(targets["codex"])
        self.assertFalse(targets["claude"])
        self.assertFalse(targets["omo"])

    def test_tokscale_follows_its_config_directory(self) -> None:
        # Given Tokscale, which ships no CLI on PATH.
        with tempfile.TemporaryDirectory() as tmp:
            present = Path(tmp) / "present"
            present.mkdir()
            for config_dir, expected in ((present, True), (Path(tmp) / "absent", False)):
                with self.subTest(config_dir=config_dir.name), \
                        patch.object(pull.shutil, "which", lambda name, path=None: None), \
                        patch.object(pull, "get_tokscale_config_dir", lambda: config_dir):
                    # When targets are detected.
                    targets = pull.detect_targets()
                # Then its configuration directory decides.
                self.assertEqual(targets["tokscale"], expected)

    def test_force_enables_every_target_without_any_agent(self) -> None:
        # Given a machine with nothing installed.
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(Path, "home", return_value=Path(tmp)), \
                patch.object(pull.shutil, "which", lambda name, path=None: None):
            # When detection is forced.
            targets = pull.detect_targets(force=True)
        # Then every known target is enabled.
        self.assertEqual(set(targets), set(pull.TARGET_LABELS))
        self.assertTrue(all(targets.values()))

    def test_report_names_detected_and_skipped_targets(self) -> None:
        # Given a machine with Codex but no Claude Code.
        targets = {name: name == "codex" for name in pull.TARGET_LABELS}
        with contextlib.redirect_stdout(io.StringIO()) as out, \
                contextlib.redirect_stderr(io.StringIO()) as err:
            pull.report_targets(targets)
        # Then both sides are named and the escape hatch is offered.
        self.assertIn("Codex", out.getvalue())
        self.assertIn("Claude Code", err.getvalue())
        self.assertIn("--all", out.getvalue())

    def test_report_is_quiet_about_skipping_when_everything_is_detected(self) -> None:
        # Given a machine with every agent installed.
        targets = {name: True for name in pull.TARGET_LABELS}
        with contextlib.redirect_stdout(io.StringIO()) as out, \
                contextlib.redirect_stderr(io.StringIO()) as err:
            pull.report_targets(targets)
        # Then nothing is reported as skipped.
        self.assertEqual(err.getvalue(), "")
        self.assertNotIn("--all", out.getvalue())


class InstallGatingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(pull, "NO_BACKUP", True))
        self.enterContext(patch.object(pull, "INSTALL_ALL", False))
        for name in ("get_config_dir", "get_omo_dir", "get_omo_agent_dir", "get_codex_dir",
                     "get_claude_config_dir", "get_omp_agent_dir", "get_tokscale_config_dir"):
            self.enterContext(patch.object(pull, name, return_value=self.tmp / name))
        self.enterContext(patch.object(Path, "home", return_value=self.tmp))
        self.wakatime = self.enterContext(patch.object(pull, "ensure_wakatime_plugins"))
        # Never reach the developer's real ~/.wakatime.cfg.
        self.wakatime_config = self.enterContext(patch.object(pull, "ensure_wakatime_config"))
        self.tokscale = self.enterContext(patch.object(pull, "install_tokscale_model_aliases"))

        def clone(command, **kwargs):
            destination = Path(command[-1])
            destination.mkdir()
            for name in ("opencode.jsonc", "omo.jsonc", "omp_config.yml", "omp_models.yaml",
                         "_AGENTS.md", "tui.json", "codex-gotify-notify.py",
                         "omp-gotify-notify.js", "omp-wakatime-sync.js"):
                _ = shutil.copy2(ROOT / name, destination / name)
            _ = shutil.copytree(ROOT / "skills", destination / "skills")
            return subprocess.CompletedProcess(command, 0)

        self.enterContext(patch.object(pull.subprocess, "run", side_effect=clone))

    def run_main(self, argv=None, **detected):
        """Run the installer with a fixed detection result."""
        targets = {name: detected.get(name, False) for name in pull.TARGET_LABELS}
        with patch.object(pull, "detect_targets", return_value=targets), \
                contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            pull.main(argv if argv is not None else [])
        return targets

    def target_dir(self, name: str) -> Path:
        return self.tmp / name

    def test_only_detected_targets_are_written(self) -> None:
        # Given a machine with OpenCode but nothing else.
        with patch.dict(os.environ, {"CODEX_BASE_URL": "https://example.invalid/v1"}):
            self.run_main(opencode=True)
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
        with patch.dict(os.environ, {"CODEX_BASE_URL": "https://example.invalid/v1"}):
            self.run_main(omo=True)
        # Then the shared OMO config and the native agent files are installed.
        self.assertTrue((self.target_dir("get_omo_dir") / "omo.jsonc").is_file())
        agent_dir = self.target_dir("get_omo_agent_dir")
        for name in ("AGENTS.md", "models.json", "settings.json"):
            self.assertTrue((agent_dir / name).is_file(), name)
        # And OpenCode itself is left alone.
        self.assertFalse(self.target_dir("get_config_dir").exists())

    def test_opencode_only_machine_does_not_create_native_agent_dir(self) -> None:
        with patch.dict(os.environ, {"CODEX_BASE_URL": "https://example.invalid/v1"}):
            self.run_main(opencode=True)
        self.assertTrue((self.target_dir("get_omo_dir") / "omo.jsonc").is_file())
        self.assertFalse(self.target_dir("get_omo_agent_dir").exists())

    def test_codex_only_machine_leaves_the_other_agents_alone(self) -> None:
        # Given a machine with Codex but nothing else.
        with patch.dict(os.environ, {"CODEX_BASE_URL": "https://example.invalid/v1"}):
            self.run_main(codex=True)
        # Then Codex is configured.
        self.assertTrue((self.target_dir("get_codex_dir") / "config.toml").is_file())
        self.assertTrue((self.target_dir("get_codex_dir") / "AGENTS.md").is_file())
        # And the OpenCode, OMO, and oh-my-pi directories are never created.
        for name in ("get_config_dir", "get_omo_dir", "get_omp_agent_dir"):
            self.assertFalse(self.target_dir(name).exists(), name)

    def test_omp_only_machine_gets_both_extensions(self) -> None:
        # Given a machine with oh-my-pi but nothing else.
        with patch.dict(os.environ, {"CODEX_BASE_URL": "https://example.invalid/v1"}):
            self.run_main(omp=True)
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
        with patch.object(pull, "NO_BACKUP", False), \
                patch.dict(os.environ, {"CODEX_BASE_URL": "https://example.invalid/v1"}):
            self.run_main(omp=True)
        # Then OMP's native user-level AGENTS.md holds the shared rules.
        self.assertEqual((agent_dir / "AGENTS.md").read_bytes(), (ROOT / "_AGENTS.md").read_bytes())
        # And the edited copy is kept as a backup, like other user-editable config.
        backups = list(agent_dir.glob("AGENTS.md.bak-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), "local rules\n")

    def test_omp_gets_repo_skills_and_keeps_user_skills(self) -> None:
        # Given OMP skills: one of the user's own, a stale copy of a managed one,
        # and autolearn output, which lives in a separate directory.
        agent_dir = self.target_dir("get_omp_agent_dir")
        own = agent_dir / "skills" / "my-skill" / "SKILL.md"
        stale = agent_dir / "skills" / "github-cli" / "removed.md"
        learned = agent_dir / "managed-skills" / "learned" / "SKILL.md"
        for path in (own, stale, learned):
            path.parent.mkdir(parents=True, exist_ok=True)
            _ = path.write_text("kept\n", encoding="utf-8")
        with patch.dict(os.environ, {"CODEX_BASE_URL": "https://example.invalid/v1"}):
            self.run_main(omp=True)
        # Then every repo skill is installed in OMP's native user skills directory.
        for skill in (ROOT / "skills").iterdir():
            self.assertEqual((agent_dir / "skills" / skill.name / "SKILL.md").read_bytes(),
                             (skill / "SKILL.md").read_bytes(), skill.name)
        # And managed skills are replaced whole, while other skills are left alone.
        self.assertFalse(stale.exists())
        self.assertEqual(own.read_text(encoding="utf-8"), "kept\n")
        self.assertEqual(learned.read_text(encoding="utf-8"), "kept\n")

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
        with patch.object(pull, "NO_BACKUP", False), \
                patch.dict(os.environ, {"CODEX_BASE_URL": "https://example.invalid/v1"}):
            self.run_main(omp=True, codex=True)
        # Then every file is updated from the repo.
        self.assertEqual((codex_dir / "AGENTS.md").read_bytes(), (ROOT / "_AGENTS.md").read_bytes())
        for path in list(stale)[1:]:
            self.assertEqual(path.read_bytes(), (ROOT / path.name).read_bytes(), path.name)
        # And only the user-editable config keeps a backup.
        self.assertEqual(len(list(codex_dir.glob("AGENTS.md.bak-*"))), 1)
        self.assertEqual(list(codex_dir.glob("codex-gotify-notify.py.bak-*")), [])
        self.assertEqual(list(extensions.glob("*.bak-*")), [])

    def test_claude_instructions_preserve_existing_user_memory(self) -> None:
        # Existing personal instructions must remain separate from the shared rules.
        claude_dir = self.target_dir("get_claude_config_dir")
        rules_dir = claude_dir / "rules"
        rules_dir.mkdir(parents=True)
        personal = claude_dir / "CLAUDE.md"
        _ = personal.write_text("Personal instructions\n", encoding="utf-8")
        managed = rules_dir / "oma-dotfile.md"
        _ = managed.write_text("Old shared instructions\n", encoding="utf-8")

        with patch.object(pull, "NO_BACKUP", False):
            self.run_main(claude=True)
            self.assertEqual(managed.read_text(encoding="utf-8"),
                             (ROOT / "_AGENTS.md").read_text(encoding="utf-8"))
            self.assertEqual(personal.read_text(encoding="utf-8"),
                             "Personal instructions\n")
            backups = list(rules_dir.glob("oma-dotfile.md.bak-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"),
                             "Old shared instructions\n")

            self.run_main(claude=True)
            self.assertEqual(list(rules_dir.glob("oma-dotfile.md.bak-*")), backups)

    def test_wakatime_step_follows_either_agent(self) -> None:
        # Given each combination of the two agents that carry a WakaTime plugin.
        for detected, expected_calls in (({"codex": True}, 1), ({"claude": True}, 1),
                                         ({"codex": True, "claude": True}, 1), ({}, 0)):
            with self.subTest(detected=sorted(detected)):
                self.wakatime.reset_mock()
                with patch.dict(os.environ, {"CODEX_BASE_URL": "https://example.invalid/v1"}):
                    self.run_main(**detected)
                # Then the step runs whenever at least one of them is installed.
                self.assertEqual(self.wakatime.call_count, expected_calls)

    def test_wakatime_config_follows_any_tracked_agent(self) -> None:
        # Given each agent alone; OMO Native and Tokscale have no WakaTime integration.
        for name in pull.TARGET_LABELS:
            with self.subTest(target=name):
                self.wakatime_config.reset_mock()
                self.wakatime.reset_mock()
                with patch.dict(os.environ, {"CODEX_BASE_URL": "https://example.invalid/v1"}):
                    self.run_main(**{name: True})
                # Then the cfg is rendered for every agent that WakaTime tracks.
                tracked = name in ("opencode", "omp", "codex", "claude")
                self.assertEqual(self.wakatime_config.call_count, int(tracked))
                # And plugins are still installed only for Codex and Claude Code.
                self.assertEqual(self.wakatime.call_count, int(name in ("codex", "claude")))

    def test_nothing_detected_writes_nothing_but_still_clones(self) -> None:
        # Given a machine with no agent at all.
        self.run_main()
        # Then the run completes without creating a single target directory.
        for name in ("get_config_dir", "get_omo_dir", "get_codex_dir",
                     "get_claude_config_dir", "get_omp_agent_dir"):
            self.assertFalse(self.target_dir(name).exists(), name)

    def test_all_flag_installs_every_target_without_detection(self) -> None:
        # Given nothing installed and no detectable agent.
        with patch.object(pull.shutil, "which", lambda name, path=None: None), \
                patch.dict(os.environ, {"CODEX_BASE_URL": "https://example.invalid/v1"}), \
                contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            # When the installer is forced.
            pull.main(["--all"])
        # Then every target directory is written anyway.
        for name in ("get_config_dir", "get_omo_dir", "get_codex_dir", "get_omp_agent_dir"):
            self.assertTrue(self.target_dir(name).is_dir(), name)
        self.wakatime.assert_called_once()
        self.tokscale.assert_called_once()

    def test_install_all_environment_variable_matches_the_flag(self) -> None:
        # Given INSTALL_ALL=1 instead of the flag, as the piped curl install would use.
        with patch.object(pull, "INSTALL_ALL", True), \
                patch.object(pull.shutil, "which", lambda name, path=None: None), \
                patch.dict(os.environ, {"CODEX_BASE_URL": "https://example.invalid/v1"}), \
                contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            pull.main([])
        # Then every target is installed just as --all does.
        for name in ("get_config_dir", "get_omo_dir", "get_codex_dir", "get_omp_agent_dir"):
            self.assertTrue(self.target_dir(name).is_dir(), name)

    def test_legacy_opencode_files_are_retired_with_opencode(self) -> None:
        # Given legacy configuration left in both OpenCode and OMO directories.
        config_dir = pull.prepare_target_dir(self.target_dir("get_config_dir"))
        omo_dir = pull.prepare_target_dir(self.target_dir("get_omo_dir"))
        legacy_opencode = config_dir / pull.LEGACY_OPENAGENT_CONFIG_NAMES[0]
        legacy_omo = omo_dir / pull.LEGACY_OMO_CONFIG_NAMES[0]
        for legacy in (legacy_opencode, legacy_omo):
            _ = legacy.write_text("{}\n", encoding="utf-8")
        # When OpenCode is detected.
        with patch.dict(os.environ, {"CODEX_BASE_URL": "https://example.invalid/v1"}):
            self.run_main(opencode=True)
        # Then both legacy files are retired, including the OpenCode one that used to be
        # retired from inside the OMO step.
        self.assertFalse(legacy_opencode.exists())
        self.assertFalse(legacy_omo.exists())


if __name__ == "__main__":
    unittest.main()
