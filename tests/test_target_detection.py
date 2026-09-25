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
        for name in ("get_config_dir", "get_omo_dir", "get_codex_dir",
                     "get_claude_config_dir", "get_omp_agent_dir", "get_tokscale_config_dir"):
            self.enterContext(patch.object(pull, name, return_value=self.tmp / name))
        self.enterContext(patch.object(Path, "home", return_value=self.tmp))
        self.wakatime = self.enterContext(patch.object(pull, "ensure_wakatime_plugins"))
        self.tokscale = self.enterContext(patch.object(pull, "install_tokscale_model_aliases"))

        def clone(command, **kwargs):
            destination = Path(command[-1])
            destination.mkdir()
            for name in ("opencode.jsonc", "omo.jsonc", "omp_config.yml", "omp_models.yaml",
                         "_AGENTS.md", "tui.json", "codex-gotify-notify.py"):
                _ = shutil.copy2(ROOT / name, destination / name)
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
