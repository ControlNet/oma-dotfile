"""The higher-order building blocks: warns_on/Skip, Codec + Files.update, @step, found_any, requires."""

import contextlib
import io
from pathlib import Path
import tempfile
import unittest

from omadotfile.core.codec import JSON, JSONC, LINES, TEXT
from unittest.mock import patch

from omadotfile.core.errors import Skip, skips, warns_on
from omadotfile.core.files import Files
from omadotfile.core.proc import Runner
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


class CodecTests(TestCase):
    def test_round_trips(self):
        self.assertEqual(JSON.load('{"a": [1]}'), {"a": [1]})
        self.assertEqual(JSON.dump({"a": "é"}), '{\n  "a": "é"\n}\n')
        self.assertEqual(JSONC.load('{"a": 1, // c\n}'), {"a": 1})
        self.assertEqual(LINES.load("a\nb\n"), ["a", "b"])
        self.assertEqual(LINES.dump(["a", "b"]), "a\nb\n")
        self.assertEqual(TEXT.load("x"), TEXT.dump("x"))

    def test_object_codecs_reject_other_json(self):
        for codec in (JSON, JSONC):
            with self.subTest(codec=codec), self.assertRaises(ValueError):
                codec.load("[]")


class FilesUpdateTests(TestCase):
    def setUp(self):
        self.dir = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.files = Files("20261107-120000", backup=True)
        self.dst = self.dir / "settings.json"

    def test_missing_file_starts_from_default(self):
        changed = self.files.update(self.dst, JSON, lambda value: {**value, "a": 1}, default={})
        self.assertTrue(changed)
        self.assertEqual(JSON.load(self.dst.read_text()), {"a": 1})

    def test_equal_value_is_not_written_even_if_formatted_differently(self):
        self.dst.write_text('{"a":1}')
        changed = self.files.update(self.dst, JSON, lambda value: dict(value), default={})
        self.assertFalse(changed)
        self.assertEqual(self.dst.read_text(), '{"a":1}')
        self.assertEqual(self.files.changed, [])

    def test_changed_value_is_backed_up_and_recorded(self):
        self.dst.write_text('{"a": 1}')
        self.files.update(self.dst, JSON, lambda value: {**value, "a": 2}, default={})
        self.assertEqual(self.dir.joinpath("settings.json.bak-20261107-120000").read_text(), '{"a": 1}')
        self.assertEqual(self.files.changed, [self.dst])

    def test_errors_from_load_or_transform_propagate_and_nothing_is_written(self):
        self.dst.write_text("[]")
        with self.assertRaises(ValueError):
            self.files.update(self.dst, JSON, lambda value: value, default={})

        def reject(value: dict) -> dict:
            raise ValueError("no")

        self.dst.write_text("{}")
        with self.assertRaises(ValueError):
            self.files.update(self.dst, JSON, reject, default={})
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
