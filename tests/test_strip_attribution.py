"""Tests for the Claude Code plugin that strips attribution from commit commands.

Commands, commit messages and hook payloads are synthetic. Nothing runs git or Claude,
and plugins are installed into a temporary dir.
"""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "claude-plugins" / "strip-attribution"
SCRIPT = PLUGIN / "scripts" / "strip_attribution.py"
SPEC = importlib.util.spec_from_file_location("strip_attribution", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
strip = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(strip)

CO_AUTHOR = "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
GENERATED = "🤖 Generated with [Claude Code](https://claude.com/claude-code)"
SESSION_LINK = "https://claude.ai/code/session_01HZM4VS8bUHLMVZet1aJGSD"
SESSION = f"Claude-Session: {SESSION_LINK}"


class StripCommandTests(unittest.TestCase):
    def test_heredoc_commit_message(self):
        command = ("git commit -q -F - <<'EOF'\nFix the thing\n\nBody line.\n\n"
                   f"{GENERATED}\n\n{CO_AUTHOR}\n{SESSION}\nEOF\ngit push -q origin master")
        self.assertEqual(strip.strip_command(command),
                         "git commit -q -F - <<'EOF'\nFix the thing\n\nBody line.\n\n\nEOF\n"
                         "git push -q origin master")

    def test_closing_quote_on_the_attribution_line_is_kept(self):
        command = f'git commit -m "Fix the thing\n\n{CO_AUTHOR}"'
        self.assertEqual(strip.strip_command(command), 'git commit -m "Fix the thing\n\n"')
        command = f"git commit -m \"$(cat <<'EOF'\nFix\n\n{SESSION}\nEOF\n)\""
        self.assertEqual(strip.strip_command(command), "git commit -m \"$(cat <<'EOF'\nFix\n\nEOF\n)\"")

    def test_command_after_the_closing_quote_is_kept(self):
        command = f'git commit -m "Fix\n\n{CO_AUTHOR}" && git push origin master'
        self.assertEqual(strip.strip_command(command), 'git commit -m "Fix\n\n" && git push origin master')

    def test_separate_message_and_trailer_arguments(self):
        command = f'git commit -m "Fix the thing" -m "{CO_AUTHOR}" -m \'{SESSION}\''
        self.assertEqual(strip.strip_command(command), 'git commit -m "Fix the thing"')
        command = f'git commit -m "Fix" --trailer "{CO_AUTHOR}" --trailer="Reviewed-by: Alice <a@example.com>"'
        self.assertEqual(strip.strip_command(command),
                         'git commit -m "Fix" --trailer="Reviewed-by: Alice <a@example.com>"')

    def test_pull_request_body(self):
        command = f'gh pr create --title "Fix" --body "Summary.\n\n{GENERATED}"'
        self.assertEqual(strip.strip_command(command), 'gh pr create --title "Fix" --body "Summary.\n\n"')
        # Claude Code asks for the bare session link at the end of PR descriptions.
        command = f'gh pr edit 7 --body "Summary.\n\n{SESSION_LINK}"'
        self.assertEqual(strip.strip_command(command), 'gh pr edit 7 --body "Summary.\n\n"')

    def test_other_trailers_and_mentions_are_kept(self):
        command = ('git commit -m "Fix\n\nCo-Authored-By: Alice <alice@example.com>\n'
                   'Mention Claude-Session: lines in docs"')
        self.assertIsNone(strip.strip_command(command))

    def test_commands_that_do_not_commit_are_left_alone(self):
        for command in (f"git log | grep '{CO_AUTHOR}'",
                        f"cat > notes.md <<'EOF'\n{CO_AUTHOR}\nEOF",
                        f"echo '{SESSION}'"):
            self.assertIsNone(strip.strip_command(command), command)

    def test_nothing_to_strip_gives_none(self):
        self.assertIsNone(strip.strip_command('git commit -m "Fix the thing"'))


class MessageFileTests(unittest.TestCase):
    def setUp(self):
        self.cwd = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_message_file_is_cleaned_in_place(self):
        message = self.cwd / "msg.txt"
        _ = message.write_text(f"Fix\n\nBody.\n\n{CO_AUTHOR}\n", encoding="utf-8")
        for command in ("git commit -F msg.txt", "git commit --file=msg.txt", 'git commit -F "msg.txt"',
                        f"git commit -F {message}"):
            _ = message.write_text(f"Fix\n\nBody.\n\n{CO_AUTHOR}\n", encoding="utf-8")
            strip.clean_message_files(command, str(self.cwd))
            self.assertEqual(message.read_text(encoding="utf-8"), "Fix\n\nBody.\n\n", command)

    def test_pull_request_body_file_is_cleaned(self):
        body = self.cwd / "body.md"
        _ = body.write_text(f"Summary.\n\n{GENERATED}\n", encoding="utf-8")
        strip.clean_message_files("gh pr create --title Fix --body-file body.md", str(self.cwd))
        self.assertEqual(body.read_text(encoding="utf-8"), "Summary.\n\n")

    def test_unchanged_or_missing_files_are_not_written(self):
        message = self.cwd / "msg.txt"
        _ = message.write_text("Fix\n", encoding="utf-8")
        before = message.stat().st_mtime_ns
        strip.clean_message_files("git commit -F msg.txt -F missing.txt -F -", str(self.cwd))
        self.assertEqual(message.stat().st_mtime_ns, before)

    def test_files_of_other_commands_are_left_alone(self):
        notes = self.cwd / "notes.md"
        _ = notes.write_text(f"{CO_AUTHOR}\n", encoding="utf-8")
        strip.clean_message_files("grep -F notes.md other.md", str(self.cwd))
        self.assertEqual(notes.read_text(encoding="utf-8"), f"{CO_AUTHOR}\n")


class HookProtocolTests(unittest.TestCase):
    def run_hook(self, payload) -> subprocess.CompletedProcess:
        stdin = payload if isinstance(payload, str) else json.dumps(payload)
        return subprocess.run([sys.executable, str(SCRIPT)], input=stdin, capture_output=True,
                              text=True, timeout=30)

    def test_rewritten_command_is_returned_without_a_permission_decision(self):
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": "/",
                   "tool_input": {"command": f'git commit -m "Fix" -m "{CO_AUTHOR}"',
                                  "description": "Commit"}}
        result = self.run_hook(payload)
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)["hookSpecificOutput"]
        # Without permissionDecision, the user's permission rules still decide.
        self.assertEqual(output, {"hookEventName": "PreToolUse",
                                  "updatedInput": {"command": 'git commit -m "Fix"',
                                                   "description": "Commit"}})

    def test_nothing_to_change_prints_nothing(self):
        payload = {"tool_name": "Bash", "cwd": "/", "tool_input": {"command": "git status"}}
        result = self.run_hook(payload)
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_bad_input_never_blocks_the_command(self):
        for payload in ("not json", "[]", {"tool_input": "x"}, {"tool_input": {"command": 3}}):
            result = self.run_hook(payload)
            self.assertEqual((result.returncode, result.stdout), (0, ""), payload)


class PluginManifestTests(unittest.TestCase):
    def test_hook_runs_before_every_bash_command(self):
        manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "strip-attribution")
        hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        self.assertEqual(list(hooks), ["PreToolUse"])
        [entry] = hooks["PreToolUse"]
        self.assertEqual(entry["matcher"], "Bash")
        [handler] = entry["hooks"]
        # It must finish before the command runs, so it is not async.
        self.assertNotIn("async", handler)
        self.assertEqual(handler["args"], ["${CLAUDE_PLUGIN_ROOT}/scripts/strip_attribution.py"])

    def test_installed_next_to_the_other_plugins_with_this_python(self):
        spec = importlib.util.spec_from_file_location("pull_strip_attribution", ROOT / "pull.py")
        assert spec is not None and spec.loader is not None
        pull = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pull)
        claude = Path(self.enterContext(tempfile.TemporaryDirectory()))
        with contextlib.redirect_stdout(io.StringIO()):
            pull.install_claude_plugins(ROOT, claude, "test")
        installed = claude / "skills" / "strip-attribution"
        self.assertEqual((installed / "scripts" / "strip_attribution.py").read_bytes(), SCRIPT.read_bytes())
        hooks = json.loads((installed / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        self.assertEqual(hooks["PreToolUse"][0]["hooks"][0]["command"], sys.executable)
        self.assertTrue((claude / "skills" / "gotify-notify" / ".claude-plugin" / "plugin.json").is_file())


if __name__ == "__main__":
    unittest.main()
