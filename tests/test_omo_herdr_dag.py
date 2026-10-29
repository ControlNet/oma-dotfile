"""omo-herdr-dag install tests.

Package and agent directories are synthetic layouts in temporary directories; the file
contents are fake stand-ins, not upstream code. npm, node and herdr are never run.
"""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pull_omo_herdr_dag", ROOT / "pull.py")
assert SPEC is not None and SPEC.loader is not None
pull = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pull)

MARKER = "// managed by omo-herdr-dag"
FAKE_DIST = {
    "extension.mjs": "export default function fake() {}\n",
    "LICENSE": "fake license\n",
    "src/model.mjs": "export const fake = 1;\n",
    "src/nested/view.mjs": "export const view = 2;\n",
    "scripts/install.mjs": "// installer is not part of a generation\n",
}


def write_tree(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def write_tgz(path: Path, members: dict[str, str]) -> Path:
    with tarfile.open(path, "w:gz") as archive:
        for name, text in members.items():
            data = text.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return path


def install_generation(agent_dir: Path, dist: Path, generation: str = "generation-000001") -> Path:
    """Lay out what upstream's install.mjs writes for one generation."""
    container = agent_dir / "herdr-dag" / "integration"
    target = container / generation
    write_tree(target, {name: text for name, text in FAKE_DIST.items() if not name.startswith("scripts/")})
    (target / "locale.json").write_text('{"language":"en"}\n', encoding="utf-8")
    (container / ".installed-by").write_text(MARKER, encoding="utf-8")
    (container / "current.json").write_text(json.dumps({"generation": generation}) + "\n", encoding="utf-8")
    wrapper = agent_dir / "extensions" / "omo-herdr-dag.js"
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text(
        f"{MARKER}\nexport {{ default }} from '../herdr-dag/integration/{generation}/extension.mjs';\n",
        encoding="utf-8",
    )
    return target


class InstallStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.dist = self.tmp / "package" / "dist"
        write_tree(self.dist, FAKE_DIST)
        self.agent = self.tmp / "agent"

    def state(self) -> str:
        return pull.herdr_dag_install_state(self.dist, self.agent)

    def test_fresh_agent_dir_is_missing(self):
        self.assertEqual(self.state(), "missing")

    def test_identical_generation_is_current(self):
        install_generation(self.agent, self.dist)
        self.assertEqual(self.state(), "current")

    def test_changed_module_is_stale(self):
        target = install_generation(self.agent, self.dist)
        (target / "src" / "model.mjs").write_text("export const fake = 0;\n", encoding="utf-8")
        self.assertEqual(self.state(), "stale")

    def test_new_module_in_package_is_stale(self):
        install_generation(self.agent, self.dist)
        write_tree(self.dist, {"src/added.mjs": "export {};\n"})
        self.assertEqual(self.state(), "stale")

    def test_wrapper_pointing_at_older_generation_is_stale(self):
        install_generation(self.agent, self.dist, "generation-000001")
        install_generation(self.agent, self.dist, "generation-000002")
        (self.agent / "extensions" / "omo-herdr-dag.js").write_text(
            f"{MARKER}\nexport {{ default }} from '../herdr-dag/integration/generation-000001/extension.mjs';\n",
            encoding="utf-8",
        )
        self.assertEqual(self.state(), "stale")

    def test_hand_written_wrapper_is_unmanaged(self):
        wrapper = self.agent / "extensions" / "omo-herdr-dag.js"
        wrapper.parent.mkdir(parents=True)
        wrapper.write_text("export default function mine() {}\n", encoding="utf-8")
        self.assertEqual(self.state(), "unmanaged")

    def test_integration_dir_without_marker_is_unmanaged(self):
        (self.agent / "herdr-dag" / "integration").mkdir(parents=True)
        self.assertEqual(self.state(), "unmanaged")


class ExtractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def tarball(self, members: dict[str, str]) -> Path:
        return write_tgz(self.tmp / "pkg.tgz", members)

    def test_extracts_package_root(self):
        tgz = self.tarball({"package/bin/omo-herdr-dag.mjs": "// fake\n", "package/dist/LICENSE": "x\n"})
        package = pull.extract_npm_package(tgz, self.tmp / "out")
        self.assertEqual(package, self.tmp / "out" / "package")
        self.assertTrue((package / "dist" / "LICENSE").is_file())

    def test_rejects_member_escaping_the_package(self):
        tgz = self.tarball({"package/bin/omo-herdr-dag.mjs": "// fake\n", "package/../evil.txt": "x\n"})
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertIsNone(pull.extract_npm_package(tgz, self.tmp / "out"))
        self.assertFalse((self.tmp / "out" / "evil.txt").exists())
        self.assertFalse((self.tmp / "evil.txt").exists())


class EnsureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.agent = self.tmp / "agent"
        self.work = self.tmp / "work"
        self.work.mkdir()
        self.commands = []
        self.found = {"herdr", "node", "npm"}
        self.enterContext(patch.object(
            pull, "find_agent_executable",
            side_effect=lambda name: Path("/fake/bin") / name if name in self.found else None))
        self.enterContext(patch.object(pull, "read_plugin_json", side_effect=self.fake_npm_pack))
        self.enterContext(patch.object(pull, "run_plugin_command", side_effect=self.fake_run))

    def fake_npm_pack(self, command, env_var, config_dir):
        self.commands.append(command)
        destination = Path(command[command.index("--pack-destination") + 1])
        members = {f"package/dist/{name}": text for name, text in FAKE_DIST.items()}
        members["package/bin/omo-herdr-dag.mjs"] = "// fake\n"
        tgz = write_tgz(destination / "omo-herdr-dag-fake.tgz", members)
        return [{"filename": tgz.name}]

    def fake_run(self, command, env_var, config_dir):
        self.commands.append(command)
        return True

    def ensure(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            pull.ensure_omo_herdr_dag(self.agent, self.work)

    def installs(self):
        return [command for command in self.commands if "install" in command]

    def test_missing_install_runs_upstream_installer_with_agent_dir(self):
        self.ensure()
        pack = self.commands[0]
        self.assertEqual(pack[:3], ["npm", "pack", f"omo-herdr-dag@{pull.OMO_HERDR_DAG_VERSION}"])
        (install,) = self.installs()
        self.assertEqual(install[0], "node")
        self.assertTrue(install[1].endswith("package/bin/omo-herdr-dag.mjs"))
        self.assertEqual(install[2:], ["install", "--agent-dir", str(self.agent)])
        self.assertNotIn("--lang", install)

    def test_current_install_is_left_alone(self):
        dist = self.tmp / "dist"
        write_tree(dist, FAKE_DIST)
        install_generation(self.agent, dist)
        self.ensure()
        self.assertEqual(self.installs(), [])

    def test_unmanaged_wrapper_is_not_overwritten(self):
        wrapper = self.agent / "extensions" / "omo-herdr-dag.js"
        wrapper.parent.mkdir(parents=True)
        wrapper.write_text("export default function mine() {}\n", encoding="utf-8")
        self.ensure()
        self.assertEqual(self.installs(), [])

    def test_skipped_without_herdr(self):
        self.found.discard("herdr")
        self.ensure()
        self.assertEqual(self.commands, [])

    def test_skipped_without_npm(self):
        self.found.discard("npm")
        self.ensure()
        self.assertEqual(self.commands, [])


if __name__ == "__main__":
    unittest.main()
