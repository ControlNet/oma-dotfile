"""The higher-order building blocks: warns_on/Skip, Codec + Files.update, @step, found_any, requires,
and dependency injection (@inject by type, @uses with explicit providers)."""

import contextlib
import inspect
import io
from pathlib import Path
import subprocess
import tempfile
import unittest

from omadotfile.core.codec import JSON, JSONC, LINES, TEXT
from unittest.mock import patch

from omadotfile.core.errors import Skip, skips, warns_on
from omadotfile.core.files import Files
from omadotfile.core import proc
from omadotfile.core.proc import CommandFailed, Runner
from omadotfile import inject as injection
from omadotfile.context import Options
from omadotfile.inject import MAX_INJECTED, home_of, inject, options_of, repo_of, runner_of, uses
from omadotfile.step import FunctionStep, Step, found_any, requires, step
from support import TestCase, make_context


def quietly(function, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
        result = function(*args, **kwargs)
    return result, err.getvalue()


class WarnsOnTests(TestCase):
    def test_expected_error_becomes_a_warning_and_none(self):
        @warns_on(OSError, ValueError, message="Failed to read {path} ({error}): {reason}")
        def read(path: str) -> str:
            raise ValueError("bad value")

        result, err = quietly(read, "a.json")

        self.assertIsNone(result)
        self.assertIn("Failed to read a.json (ValueError): bad value", err)

    def test_result_passes_through_and_metadata_is_kept(self):
        @warns_on(OSError, message="never")
        def double(value: int) -> int:
            """Double it."""
            return value * 2

        self.assertEqual(double(value=4), 8)
        self.assertEqual(double.__name__, "double")
        self.assertEqual(double.__doc__, "Double it.")

    def test_other_errors_propagate(self):
        @warns_on(OSError, message="never")
        def broken() -> None:
            raise KeyError("x")

        with self.assertRaises(KeyError):
            broken()

    def test_unknown_message_field_fails_at_decoration(self):
        with self.assertRaises(TypeError):
            @warns_on(OSError, message="Failed to read {dst}")
            def read(path: str) -> None:
                pass


class SkipTests(TestCase):
    def test_skip_message_is_printed_verbatim_and_the_call_returns_none(self):
        @skips
        def install(path: str) -> str:
            raise Skip(f"         {path} skipped: herdr not found")

        result, err = quietly(install, "dag")

        self.assertIsNone(result)
        self.assertIn("[WARN]\x1b[0m             dag skipped: herdr not found\n", err)

    def test_result_passes_through_and_other_errors_propagate(self):
        @skips
        def ok() -> int:
            return 1

        @skips
        def broken() -> None:
            raise ValueError("x")

        self.assertEqual(ok(), 1)
        with self.assertRaises(ValueError):
            broken()


class RequiresTests(TestCase):
    def setUp(self):
        self.found = {"node"}
        self.looked_up: list[str] = []

        def which(name):
            self.looked_up.append(name)
            return Path("/fake/bin") / name if name in self.found else None

        # Patched on the class: ctx.runner is a fresh Runner on every access.
        self.enterContext(patch.object(Runner, "which", side_effect=which))
        self.ctx = make_context(Path(self.enterContext(tempfile.TemporaryDirectory())))

    def test_runs_when_every_executable_is_found(self):
        @requires("node", skip="never")
        def act(ctx, value: int, *, scale: int = 1) -> int:
            return value * scale

        self.assertEqual(act(self.ctx, 2, scale=3), 6)
        self.assertEqual(act.__name__, "act")

    def test_warns_and_stops_at_the_first_missing_executable(self):
        calls = []

        @requires("node", "npm", "herdr", skip="dag skipped: node and npm are required")
        def act(ctx) -> None:
            calls.append(ctx)

        result, err = quietly(act, self.ctx)

        self.assertIsNone(result)
        self.assertEqual(calls, [])
        self.assertIn("dag skipped: node and npm are required", err)
        self.assertEqual(self.looked_up, ["node", "npm"])


class RunnerTests(TestCase):
    def setUp(self):
        self.enterContext(patch.object(proc, "find_executable", return_value=Path("/fake/bin/tool")))
        self.runner = Runner({"PATH": "/usr/bin", "A": "run"}, Path("/h"))

    def run_with(self, **completed):
        done = subprocess.CompletedProcess(["tool"], completed.pop("returncode", 0), **completed)
        return patch.object(proc.subprocess, "run", return_value=done)

    def test_pinned_runner_adds_its_env_over_the_runs(self):
        pinned = self.runner.pinned({"A": "pinned", "B": "1"}).pinned({"C": "2"})
        self.assertEqual(pinned.pin, {"A": "pinned", "B": "1", "C": "2"})
        self.assertEqual(self.runner.pin, {})  # the original is unchanged
        with self.run_with(stdout="[]", stderr="") as run:
            self.assertEqual(pinned.json(["tool", "--json"]), [])
        env = run.call_args.kwargs["env"]
        self.assertEqual((env["A"], env["B"], env["C"]), ("pinned", "1", "2"))
        self.assertEqual(env["PATH"], "/fake/bin:/usr/bin")
        self.assertEqual(run.call_args.args[0], ["/fake/bin/tool", "--json"])

    def test_each_failure_is_a_command_failed_with_the_old_warning_text(self):
        with self.run_with(returncode=3, stdout="", stderr="secret"), \
                self.assertRaisesRegex(CommandFailed, r"^/fake/bin/tool x failed with exit code 3$"):
            self.runner.run(["tool", "x"])
        with self.run_with(stdout="not json", stderr=""), \
                self.assertRaisesRegex(CommandFailed, r"^Failed to parse JSON output of tool x$"):
            self.runner.json(["tool", "x"])
        with patch.object(proc.subprocess, "run", side_effect=FileNotFoundError("no tool")), \
                self.assertRaisesRegex(CommandFailed, r"^Failed to run /fake/bin/tool x: no tool$"):
            self.runner.run(["tool", "x"])

    def test_command_failed_is_a_skip(self):
        self.assertTrue(issubclass(CommandFailed, Skip))
        self.assertFalse(hasattr(Runner, "ok"))  # stale patches of Runner.ok must fail loudly


class InjectTests(TestCase):
    def setUp(self):
        self.ctx = make_context(Path(self.enterContext(tempfile.TemporaryDirectory())), oauth=True)

    def test_dependencies_are_injected_by_type_and_the_rest_is_passed_through(self):
        @inject
        def one(files: Files, /, name: str, *, suffix: str = "") -> tuple[Files, str]:
            return files, name + suffix

        @inject
        def two(runner: Runner, options: Options, /, name: str) -> tuple[Runner, bool, str]:
            return runner, options.oauth, name

        self.assertEqual(one(self.ctx, "a", suffix="b"), (self.ctx.files, "ab"))
        runner, oauth, name = two(self.ctx, "x")
        self.assertIsInstance(runner, Runner)
        self.assertEqual((oauth, name), (True, "x"))
        self.assertEqual(one.__name__, "one")

    def test_the_wired_signature_takes_the_context_first(self):
        @inject
        def one(files: Files, /, name: str) -> str:
            return name

        self.assertEqual(list(inspect.signature(one).parameters), ["ctx", "name"])

    def test_only_the_leading_injectable_prefix_is_injected_up_to_the_maximum(self):
        @inject
        def first_only(files: Files, /, name: str, runner: Runner) -> tuple[str, Runner]:
            return name, runner

        other = Runner({}, Path("/other"))
        self.assertEqual(first_only(self.ctx, "n", other), ("n", other))
        self.assertEqual(MAX_INJECTED, 3)

    def test_misdeclared_functions_fail_when_decorated(self):
        def unregistered(home: Path, /) -> None: ...  # ambiguous type: use @uses

        def not_positional_only(files: Files, runner: Runner) -> None: ...

        def too_many(files: Files, runner: Runner, options: Options, files2: Files, /) -> None: ...

        for function, reason in ((unregistered, "@uses"), (not_positional_only, "positional-only")):
            with self.subTest(function=function.__name__), self.assertRaisesRegex(TypeError, reason):
                inject(function)
        # A fourth leading dependency stays a parameter, as pyright sees it.
        self.assertEqual(list(inspect.signature(inject(too_many)).parameters), ["ctx", "files2"])

    def test_stacking_fails_instead_of_misbinding(self):
        @inject
        def one(files: Files, /) -> None: ...

        with self.assertRaisesRegex(TypeError, "@uses"):
            inject(one)

    def test_table_and_type_constraints_name_the_same_types(self):
        for dep in (injection.Dep1, injection.Dep2, injection.Dep3):
            self.assertEqual(set(dep.__constraints__), set(injection.PROVIDERS))
        self.assertNotIn(type(self.ctx), injection.PROVIDERS)

    def test_explicit_providers_cover_ambiguous_types(self):
        @uses(home_of, repo_of)
        def paths(home: Path, repo: Path, /, name: str) -> tuple[Path, Path, str]:
            return home, repo, name

        self.assertEqual(paths(self.ctx, "n"), (self.ctx.home, self.ctx.repo, "n"))
        self.assertEqual(list(inspect.signature(paths).parameters), ["ctx", "name"])

    def test_uses_needs_positional_only_parameters_for_its_providers(self):
        def loose(runner: Runner, options: Options) -> None: ...

        with self.assertRaisesRegex(TypeError, "positional-only"):
            uses(runner_of, options_of)(loose)

    def test_inject_over_warns_on_keeps_the_message_fields(self):
        @inject
        @warns_on(OSError, message="Failed to write {dst}: {reason}")
        def write(files: Files, /, dst: Path) -> bool:
            raise OSError("disk full")

        result, err = quietly(write, self.ctx, Path("x.json"))
        self.assertIsNone(result)
        self.assertIn("Failed to write x.json: disk full", err)


class CodecTests(TestCase):
    def test_round_trips(self):
        self.assertEqual(JSON.load('{"a": [1]}'), {"a": [1]})
        self.assertEqual(JSON.dump({"a": "é"}), '{\n  "a": "é"\n}\n')
        self.assertEqual(JSONC.load('{"a": 1, // c\n}'), {"a": 1})
        self.assertEqual(LINES.load("a\nb\n"), ["a", "b"])
        self.assertEqual(LINES.dump(["a", "b"]), "a\nb\n")
        self.assertEqual(TEXT.load("x"), TEXT.dump("x"))

    def test_empty_is_a_fresh_value_that_dumps_and_loads_back(self):
        self.assertEqual((JSON.empty(), JSONC.empty(), LINES.empty(), TEXT.empty()), ({}, {}, [], ""))
        # A new object each call: a transform that mutates it cannot leak into the next update.
        for codec in (JSON, JSONC, LINES):
            with self.subTest(codec=codec):
                self.assertIsNot(codec.empty(), codec.empty())
        self.assertEqual(JSON.load(JSON.dump(JSON.empty())), {})

    def test_object_codecs_reject_other_json(self):
        for codec in (JSON, JSONC):
            with self.subTest(codec=codec), self.assertRaises(ValueError):
                codec.load("[]")


class FilesUpdateTests(TestCase):
    def setUp(self):
        self.dir = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.files = Files("20261107-120000", backup=True)
        self.dst = self.dir / "settings.json"

    def test_missing_file_starts_from_the_codecs_empty_value(self):
        changed = self.files.update(self.dst, JSON, lambda value: {**value, "a": 1})
        self.assertTrue(changed)
        self.assertEqual(JSON.load(self.dst.read_text()), {"a": 1})

    def test_equal_value_is_not_written_even_if_formatted_differently(self):
        self.dst.write_text('{"a":1}')
        changed = self.files.update(self.dst, JSON, lambda value: dict(value))
        self.assertFalse(changed)
        self.assertEqual(self.dst.read_text(), '{"a":1}')
        self.assertEqual(self.files.changed, [])

    def test_changed_value_is_backed_up_and_recorded(self):
        self.dst.write_text('{"a": 1}')
        self.files.update(self.dst, JSON, lambda value: {**value, "a": 2})
        self.assertEqual(self.dir.joinpath("settings.json.bak-20261107-120000").read_text(), '{"a": 1}')
        self.assertEqual(self.files.changed, [self.dst])

    def test_errors_from_load_or_transform_propagate_and_nothing_is_written(self):
        self.dst.write_text("[]")
        with self.assertRaises(ValueError):
            self.files.update(self.dst, JSON, lambda value: value)

        def reject(value: dict) -> dict:
            raise ValueError("no")

        self.dst.write_text("{}")
        with self.assertRaises(ValueError):
            self.files.update(self.dst, JSON, reject)
        self.assertEqual(self.dst.read_text(), "{}")


class StepTests(TestCase):
    def test_step_decorator_wraps_a_function_into_a_step(self):
        calls = []

        @step("Doing it", when=found_any("codex", "claude"), skip="nothing found")
        def do_it(ctx) -> None:
            calls.append(ctx)

        self.assertIsInstance(do_it, FunctionStep)
        self.assertIsInstance(do_it, Step)
        with tempfile.TemporaryDirectory() as tmp:
            ctx = make_context(Path(tmp), found=("claude",))
            self.assertEqual(do_it.title(ctx), "Doing it")
            self.assertTrue(do_it.enabled(ctx))
            self.assertEqual(do_it.skip_reason(ctx), "nothing found")
            do_it.run(ctx)
            self.assertEqual(calls, [ctx])
            self.assertFalse(do_it.enabled(make_context(Path(tmp), found=("omp",))))

    def test_found_any_is_a_reusable_predicate(self):
        predicate = found_any("opencode", "omo")
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(predicate(make_context(Path(tmp), found=("omo",))))
            self.assertFalse(predicate(make_context(Path(tmp), found=())))


if __name__ == "__main__":
    unittest.main()
