"""Synthetic notification events; all delivery and summarization are mocked."""

import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "codex-gotify-notify.py"
SPEC = importlib.util.spec_from_file_location("codex_gotify_notify", SCRIPT)
notify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(notify)

# Upstream rust-v0.153.4 prompt with synthetic conversation content.
RECAP_PROMPT = (
    "Write a brief catch-up for a user returning to this Codex task. "
    "In at most 40 words and one or two plain-text sentences, explain the "
    "objective, what was completed or learned, and the next step or blocker. "
    "Mention changed files, tests, approvals, or requested decisions only "
    "when relevant. Never claim changes were made or tests passed unless "
    "the conversation confirms it. If the task is complete, say so instead "
    "of inventing more work. Use the user's language; omit greetings, "
    "markdown, lists, and tool chatter.\n\nRecent conversation:\n"
    "User: Investigate recap notifications."
)


class RecapNotificationTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {
            "GOTIFY_URL": "https://gotify.invalid",
            "GOTIFY_TOKEN_FOR_CODEX": "synthetic-test-only-not-a-credential",
        }, clear=True))
        self.log = self.enterContext(patch.object(notify, "_log_line"))
        self.process_scan = self.enterContext(
            patch.object(notify, "_is_codex_acp_process_tree", return_value=False)
        )
        self.source_scan = self.enterContext(
            patch.object(notify, "_thread_source_flags", return_value={})
        )
        self.summary = self.enterContext(
            patch.object(notify, "_summarize_with_llm", return_value="Test summary")
        )
        self.dedup = self.enterContext(
            patch.object(notify, "_should_send", return_value=True)
        )
        self.push = self.enterContext(patch.object(notify, "_push_gotify"))
        self.enterContext(patch.object(
            notify.urllib.request, "urlopen",
            side_effect=AssertionError("Network access is forbidden in this test"),
        ))

    def run_event(self, prompt, *, assistant='{"recap":"Investigation complete."}'):
        payload = {
            "type": "agent-turn-complete",
            "thread-id": "synthetic-notification-thread",
            "input-messages": [prompt],
            "last-assistant-message": assistant,
        }
        with patch.object(sys, "argv", [str(SCRIPT), json.dumps(payload)]):
            self.assertEqual(notify.main(), 0)

    def assert_skipped(self, reason):
        self.process_scan.assert_not_called()
        self.source_scan.assert_not_called()
        self.summary.assert_not_called()
        self.dedup.assert_not_called()
        self.push.assert_not_called()
        self.assertTrue(any(
            f"run_skip reason={reason}" in call.args[0]
            for call in self.log.call_args_list
        ))

    def test_recap_skips_before_scans_summary_and_delivery(self):
        self.run_event(RECAP_PROMPT)
        self.assert_skipped("conversation_recap")

    def test_recap_accepts_case_and_whitespace_variations(self):
        self.run_event("\n " + RECAP_PROMPT.upper().replace(" ", "\n  "))
        self.assert_skipped("conversation_recap")

    def test_nested_stdin_payload_is_filtered(self):
        payload = {"hook_event": {
            "event_type": "after_agent",
            "input_messages": [{"type": "text", "text": RECAP_PROMPT}],
            "last_assistant_message": '{"recap":"Investigation complete."}',
        }}
        with patch.object(sys, "argv", [str(SCRIPT)]), \
                patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
            self.assertEqual(notify.main(), 0)
        self.assert_skipped("conversation_recap")

    def test_ordinary_completion_with_recap_output_still_notifies(self):
        self.run_event("Summarize our conversation.")
        self.summary.assert_called_once()
        self.push.assert_called_once()

    def test_quoted_recap_prompt_still_notifies(self):
        self.run_event("Explain this internal prompt:\n" + RECAP_PROMPT)
        self.push.assert_called_once()

    def test_partial_signatures_still_notify(self):
        for prompt in (
            RECAP_PROMPT.split("In at most", 1)[0],
            RECAP_PROMPT.replace("Recent conversation:", "Conversation:"),
            RECAP_PROMPT.replace("In at most 40 words", "In at most 80 words"),
        ):
            with self.subTest(prompt=prompt):
                self.push.reset_mock()
                self.run_event(prompt)
                self.push.assert_called_once()

    def test_non_completion_event_is_not_classified_as_recap(self):
        self.assertFalse(notify._is_conversation_recap_event({
            "type": "permission-requested", "input-messages": [RECAP_PROMPT],
        }))

    def test_title_generation_filter_is_preserved(self):
        self.run_event(
            "Generate a concise, single-line task title. "
            "Do not answer the request. User prompt: Investigate notifications."
        )
        self.assert_skipped("thread_title_generation")


if __name__ == "__main__":
    unittest.main()
