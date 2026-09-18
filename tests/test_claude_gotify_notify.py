"""Synthetic Claude events and credentials; network calls are mocked in all tests."""

import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "claude-plugins" / "gotify-notify"
SPEC = importlib.util.spec_from_file_location("claude_notify", PLUGIN / "scripts" / "notify.py")
notify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(notify)


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.dict(os.environ, {
            "CLAUDE_CONFIG_DIR": self.tmp,
            "GOTIFY_URL": "https://gotify.invalid",
            "GOTIFY_TOKEN_FOR_CLAUDE": "synthetic-test-only-not-a-credential",
        }, clear=True))
        self.post = self.enterContext(patch.object(notify, "post_json", return_value={}))
        self.enterContext(patch.object(
            notify.urllib.request, "urlopen",
            side_effect=AssertionError("Real network requests are forbidden"),
        ))

    def event(self, name="Stop", **fields):
        return {
            "hook_event_name": name, "session_id": "synthetic-session",
            "prompt_id": "synthetic-prompt", "cwd": "/work/project",
            "last_assistant_message": "Implemented the requested change.",
            **fields,
        }

    def run_event(self, payload, args=None):
        with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
            return notify.main(args or [])

    def test_stop_sends_final_reply_with_project_title(self):
        self.assertEqual(self.run_event(self.event()), 0)
        body = self.post.call_args.args[1]
        self.assertTrue(body["title"].startswith("Claude Code :: project@"))
        self.assertEqual(body["message"], "Response finished: Implemented the requested change.")

    def test_waiting_events_and_failure(self):
        for name, fields, expected in [
            ("Notification", {"notification_type": "permission_prompt", "message": "Approve command"}, "Permission needed: Approve command"),
            ("Notification", {"notification_type": "elicitation_dialog", "message": "Choose account"}, "Input needed: Choose account"),
            ("Notification", {"notification_type": "elicitation_url_dialog", "message": "Open browser"}, "Input needed: Open browser"),
            ("PreToolUse", {"tool_name": "AskUserQuestion", "tool_use_id": "question-1", "tool_input": {"questions": [{"question": "Which branch?"}]}}, "Question: Which branch?"),
            ("StopFailure", {"error": "rate_limit"}, "API error: rate_limit"),
        ]:
            with self.subTest(name=name, fields=fields):
                self.post.reset_mock()
                self.run_event(self.event(name, **fields))
                self.assertEqual(self.post.call_args.args[1]["message"], expected)

    def test_unwanted_events_and_background_work_are_ignored(self):
        for payload in [
            self.event("SubagentStop", agent_id="child"),
            self.event("PostToolUseFailure"),
            self.event("Notification", notification_type="idle_prompt"),
            self.event("Notification", notification_type="auth_success"),
            self.event("PreToolUse", tool_name="Bash"),
            self.event("PreToolUse", tool_name="AskUserQuestion", agent_id="child"),
            self.event(background_tasks=[{"status": "running"}]),
            self.event(session_crons=[{"recurring": True}]),
        ]:
            self.run_event(payload)
        self.post.assert_not_called()

    def test_stop_hook_continuation_can_still_notify(self):
        self.run_event(self.event(stop_hook_active=True))
        self.post.assert_called_once()

    def test_toggles_and_subagent_opt_in(self):
        with patch.dict(os.environ, {"CLAUDE_NOTIFY_COMPLETE": "false"}):
            self.run_event(self.event())
        self.post.assert_not_called()
        with patch.dict(os.environ, {"CLAUDE_NOTIFY_SUBAGENT": "true"}):
            self.run_event(self.event("SubagentStop", agent_id="child"))
        self.post.assert_called_once()

    def test_dedup_is_before_summary_and_separates_prompts(self):
        with patch.object(notify, "summarize", return_value="Summary") as summary:
            self.run_event(self.event())
            self.run_event(self.event())
            self.run_event(self.event(prompt_id="another-prompt"))
            self.assertEqual(self.post.call_count, 2)
            self.assertEqual(summary.call_count, 2)

    def test_failed_delivery_can_retry(self):
        self.post.side_effect = [None, {}]
        self.run_event(self.event())
        self.run_event(self.event())
        self.assertEqual(self.post.call_count, 2)

    def test_claim_excludes_concurrent_handler(self):
        self.assertTrue(notify.claim("synthetic-key"))
        self.assertFalse(notify.claim("synthetic-key"))
        notify.finish("synthetic-key", False)
        self.assertTrue(notify.claim("synthetic-key"))

    def test_missing_config_does_not_use_network_or_state(self):
        with patch.dict(os.environ, {"GOTIFY_TOKEN_FOR_CLAUDE": ""}):
            self.run_event(self.event())
        self.post.assert_not_called()
        self.assertFalse((Path(self.tmp) / "gotify-notify" / "state.sqlite3").exists())

    def test_dry_run_never_uses_network_or_state(self):
        with patch.object(sys, "stdout", io.StringIO()) as out:
            self.run_event(self.event(), ["--dry-run"])
            self.assertIn("Response finished", json.loads(out.getvalue())["message"])
        self.post.assert_not_called()
        self.assertEqual(list(Path(self.tmp).iterdir()), [])

    def test_invalid_input_exits_without_control_output(self):
        for raw in ["not json", "[]", "null", '{"hook_event_name": []}']:
            with patch.object(sys, "stdin", io.StringIO(raw)), patch.object(sys, "stdout", io.StringIO()) as out:
                self.assertEqual(notify.main([]), 0)
                self.assertEqual(out.getvalue(), "")
        self.post.assert_not_called()

    def test_summary_fallback_and_unicode_limit(self):
        with patch.dict(os.environ, {"CLAUDE_NOTIFY_MAX_CHARS": "40"}), patch.object(notify, "summarize", return_value=""):
            self.run_event(self.event(last_assistant_message="\u4fee\u590d" * 100))
        message = self.post.call_args.args[1]["message"]
        self.assertEqual(len(message), 40)
        self.assertTrue(message.endswith("..."))

    def test_summary_routes_and_incomplete_configuration(self):
        self.assertEqual(notify.summarize("Final response"), "")
        self.post.assert_not_called()
        with patch.dict(os.environ, {
            "GOTIFY_NOTIFY_SUMMARIZER_MODEL": "synthetic-model",
            "GOTIFY_NOTIFY_SUMMARIZER_ENDPOINT": "https://summary.invalid/v1",
            "GOTIFY_NOTIFY_SUMMARIZER_API_KEY": "synthetic-test-only-not-a-credential",
        }):
            self.post.side_effect = [None, {"output": [{"content": [{"text": "Concise result"}]}]}]
            self.assertEqual(notify.summarize("Final response"), "Concise result")
            self.assertTrue(self.post.call_args_list[0].args[0].endswith("/chat/completions"))
            self.assertTrue(self.post.call_args_list[1].args[0].endswith("/responses"))

    def test_network_errors_do_not_log_request_or_credentials(self):
        with patch.object(notify.urllib.request, "urlopen", side_effect=OSError("sensitive request details")):
            self.assertIsNone(self.post._mock_wraps)
            # Call the real implementation, bypassing the delivery mock.
            result = ORIGINAL_POST("https://gotify.invalid/message", {}, {}, 1, "gotify")
        self.assertIsNone(result)
        log = (Path(self.tmp) / "logs" / "gotify-notify.log").read_text()
        self.assertIn("OSError", log)
        self.assertNotIn("sensitive", log)
        self.assertNotIn("synthetic-test-only", log)


ORIGINAL_POST = notify.post_json


class PluginInstallTests(unittest.TestCase):
    def test_manifest_hooks_and_repeat_install_preserve_local_config(self):
        import pull

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            settings = target / "settings.json"
            settings.write_text('{"hooks":{}}', encoding="utf-8")
            unrelated = target / "skills" / "personal-skill" / "SKILL.md"
            unrelated.parent.mkdir(parents=True)
            unrelated.write_text("Synthetic user skill", encoding="utf-8")
            pull.install_claude_plugin(ROOT, target, "test-first")
            pull.install_claude_plugin(ROOT, target, "test-second")
            plugin = target / "skills" / "gotify-notify"
            self.assertEqual(settings.read_text(), '{"hooks":{}}')
            self.assertEqual(unrelated.read_text(), "Synthetic user skill")
            manifest = json.loads((plugin / ".claude-plugin" / "plugin.json").read_text())
            self.assertEqual(manifest["name"], "gotify-notify")
            hooks = json.loads((plugin / "hooks" / "hooks.json").read_text())["hooks"]
            self.assertEqual(set(hooks), {"Stop", "StopFailure", "Notification", "PreToolUse", "SubagentStop"})
            for entries in hooks.values():
                for entry in entries:
                    self.assertEqual(len(entry["hooks"]), 1)
                    handler = entry["hooks"][0]
                    self.assertTrue(handler["async"])
                    self.assertEqual(handler["command"], sys.executable)
                    self.assertEqual(handler["args"], ["${CLAUDE_PLUGIN_ROOT}/scripts/notify.py"])
            self.assertTrue((plugin / "scripts" / "notify.py").is_file())


if __name__ == "__main__":
    unittest.main()
