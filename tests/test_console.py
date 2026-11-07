"""Console output goes to the Console bound for the run; the Terminal is the default."""

from concurrent.futures import ThreadPoolExecutor
from contextvars import Context
import contextlib
import io
from pathlib import Path
from unittest.mock import patch

from omadotfile import console
from omadotfile.console import HomeAsTilde, Terminal, current_console, info, item, line, use_console, warn
from omadotfile.core.errors import Skip, skips, warns_on
from omadotfile.features import skills
from omadotfile.step import requires
from support import Recorder, TestCase, make_context


class BindingTests(TestCase):
    def test_the_terminal_is_the_default(self):
        # An empty context shows the default; tests otherwise run with a Recorder bound.
        self.assertIsInstance(Context().run(current_console), Terminal)

    def test_a_bound_console_gets_every_level_until_the_block_ends(self):
        with use_console(Recorder()) as recorder:
            info("i")
            console.success("s")
            warn("w")
            console.error("e")
            item("x")
            line("raw")
        self.assertEqual(recorder.lines, [("info", "i"), ("success", "s"), ("warn", "w"),
                                          ("error", "e"), ("item", "x"), ("text", "raw")])
        self.assertIs(current_console(), self.console)  # the test's own binding is back

    def test_bindings_nest(self):
        with use_console(Recorder()) as outer:
            with use_console(Recorder()) as inner:
                warn("inner")
            warn("outer")
        self.assertEqual((inner.warnings, outer.warnings), (["inner"], ["outer"]))

    def test_step_announces_and_reports_the_skip_reason(self):
        with use_console(Recorder()) as recorder:
            self.assertFalse(console.step("1/2", "Doing it", False, "not needed"))
        self.assertEqual(recorder.lines, [("info", "[1/2] Doing it"), ("warn", "         skipped: not needed")])


class DecoratorOutputTests(TestCase):
    """The decorators print through the bound Console too, though they never see the Context."""

    def test_warns_on_and_skips(self):
        @warns_on(OSError, message="Failed to write {name}: {reason}")
        def write(name: str) -> None:
            raise OSError("disk full")

        @skips
        def stop() -> None:
            raise Skip("not today")

        with use_console(Recorder()) as recorder:
            write("a.json")
            stop()
        self.assertEqual(recorder.warnings, ["Failed to write a.json: disk full", "not today"])

    def test_requires(self):
        @requires("tool-that-is-not-installed", skip="skipped: no tool")
        def action(ctx: object) -> None: ...

        with use_console(Recorder()) as recorder:
            action(make_context(Path("/h"), env={"PATH": "/nonexistent"}))
        self.assertEqual(recorder.warnings, ["skipped: no tool"])


class ThreadTests(TestCase):
    def test_parallel_commit_lookups_print_to_the_bound_console(self):
        # Worker threads start from an empty context unless the lookup carries the caller's.
        def lookup(ctx: object, source: str) -> str:
            warn(f"looked up {source}")
            return source[0] * 40

        with patch.object(skills, "ls_remote_commit", lookup), use_console(Recorder()) as recorder:
            commits = skills.remote_commits(make_context(Path("/h")), {"a/b", "c/d"})
        self.assertEqual(commits, {"a/b": "a" * 40, "c/d": "c" * 40})
        self.assertEqual(sorted(recorder.warnings), ["looked up a/b", "looked up c/d"])

    def test_a_plain_thread_pool_does_not_see_the_binding(self):
        # Why remote_commits copies the context: this is what it would do otherwise.
        with use_console(Recorder()), ThreadPoolExecutor(1) as pool:
            self.assertIsInstance(pool.submit(current_console).result(), Terminal)


class TerminalTests(TestCase):
    def test_lines_keep_their_prefixes_and_streams(self):
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            terminal = Terminal()
            terminal.emit("info", "i")
            terminal.emit("item", "x")
            terminal.emit("text", "raw")
            terminal.emit("warn", "w")
        self.assertEqual(out.getvalue(), f"{console.CYAN}{console.BOLD}[INFO]{console.RESET}    i\n"
                                         "         - x\nraw\n")
        self.assertEqual(err.getvalue(), f"{console.YELLOW}{console.BOLD}[WARN]{console.RESET}    w\n")

    def test_streams_are_looked_up_per_line(self):
        # A Terminal made before redirect_stdout still writes into the redirect.
        terminal = Terminal()
        with contextlib.redirect_stdout(io.StringIO()) as out:
            terminal.emit("success", "done")
        self.assertIn("done", out.getvalue())


class HomeAsTildeTests(TestCase):
    def shown(self, home: str, text: str) -> str:
        recorder = Recorder()
        HomeAsTilde(recorder, Path(home)).emit("info", text)
        (shown,) = recorder.of("info")
        return shown

    def test_the_home_directory_is_written_as_a_tilde(self):
        self.assertEqual(self.shown("/home/u", "Installing to: /home/u/.omp/agent"), "Installing to: ~/.omp/agent")
        self.assertEqual(self.shown("/home/u", "copy /home/u/a to /home/u/b"), "copy ~/a to ~/b")
        self.assertEqual(self.shown("/home/u", "home is /home/u"), "home is ~")
        self.assertEqual(self.shown("/home/u", "Failed to read '/home/u/x': denied"), "Failed to read '~/x': denied")

    def test_only_the_home_directory_itself(self):
        for text in ("/home/user/x", "/mnt/home/u/x", "/home/u.old/x", "/home/u-2"):
            with self.subTest(text):
                self.assertEqual(self.shown("/home/u", text), text)

    def test_a_root_home_is_left_alone(self):
        self.assertEqual(self.shown("/", "/etc/x"), "/etc/x")

    def test_the_level_is_kept(self):
        recorder = Recorder()
        HomeAsTilde(recorder, Path("/home/u")).emit("warn", "/home/u/x")
        self.assertEqual(recorder.lines, [("warn", "~/x")])
