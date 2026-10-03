"""Synthetic notification events; all delivery and summarization are mocked."""

from contextlib import closing
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
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


# Schema copied from codex-cli 0.160.0 goals_1.sqlite; rows are synthetic.
GOALS_SCHEMA = """
CREATE TABLE thread_goals (
    thread_id TEXT PRIMARY KEY NOT NULL,
    goal_id TEXT NOT NULL,
    objective TEXT NOT NULL,
    status TEXT NOT NULL,
    token_budget INTEGER,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    time_used_seconds INTEGER NOT NULL DEFAULT 0,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);
CREATE TABLE thread_goal_continuation_deferrals (
    thread_id TEXT PRIMARY KEY NOT NULL
);
"""
GOAL_THREAD = "synthetic-goal-thread"


class GoalContinuationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.goals_db = self.tmp / "goals_1.sqlite"
        self.enterContext(patch.dict(os.environ, {
            "GOTIFY_URL": "https://gotify.invalid",
            "GOTIFY_TOKEN_FOR_CODEX": "synthetic-test-only-not-a-credential",
            "CODEX_NOTIFY_GOALS_DB": str(self.goals_db),
        }, clear=True))
        self.log = self.enterContext(patch.object(notify, "_log_line"))
        self.enterContext(
            patch.object(notify, "_is_codex_acp_process_tree", return_value=False)
        )
        self.enterContext(patch.object(notify, "_thread_source_flags", return_value={}))
        self.summary = self.enterContext(
            patch.object(notify, "_summarize_with_llm", return_value="Test summary")
        )
        self.enterContext(patch.object(notify, "_should_send", return_value=True))
        self.push = self.enterContext(patch.object(notify, "_push_gotify"))
        self.enterContext(patch.object(
            notify.urllib.request, "urlopen",
            side_effect=AssertionError("Network access is forbidden in this test"),
        ))

    def write_goal(self, status, *, deferred=False):
        with closing(sqlite3.connect(self.goals_db)) as conn, conn:
            conn.executescript(GOALS_SCHEMA)
            conn.execute(
                "INSERT INTO thread_goals (thread_id, goal_id, objective, status, "
                "created_at_ms, updated_at_ms) VALUES (?, 'goal-1', 'Watch job', ?, 1, 1)",
                (GOAL_THREAD, status),
            )
            if deferred:
                conn.execute(
                    "INSERT INTO thread_goal_continuation_deferrals VALUES (?)",
                    (GOAL_THREAD,),
                )

    def run_event(self, *, event_type="agent-turn-complete"):
        payload = {
            "type": event_type,
            "thread-id": GOAL_THREAD,
            "input-messages": ["Keep watching the queue."],
            "last-assistant-message": "Queue still running; waiting for exit.",
        }
        with patch.object(sys, "argv", [str(SCRIPT), json.dumps(payload)]):
            self.assertEqual(notify.main(), 0)

    def test_active_goal_turn_is_skipped_before_summary(self):
        self.write_goal("active")
        self.run_event()
        self.summary.assert_not_called()
        self.push.assert_not_called()
        self.assertTrue(any(
            "run_skip reason=goal_continuation" in call.args[0]
            for call in self.log.call_args_list
        ))

    def test_finished_or_stopped_goal_still_notifies(self):
        for status in ("complete", "paused", "blocked", "usage_limited", "budget_limited"):
            with self.subTest(status=status):
                self.goals_db.unlink(missing_ok=True)
                self.push.reset_mock()
                self.write_goal(status)
                self.run_event()
                self.push.assert_called_once()

    def test_deferred_continuation_still_notifies(self):
        self.write_goal("active", deferred=True)
        self.run_event()
        self.push.assert_called_once()

    def test_thread_without_goal_still_notifies(self):
        self.write_goal("active")
        with closing(sqlite3.connect(self.goals_db)) as conn, conn:
            conn.execute("UPDATE thread_goals SET thread_id = 'other-thread'")
        self.run_event()
        self.push.assert_called_once()

    def test_missing_or_unreadable_goals_db_fails_open(self):
        self.run_event()
        self.push.assert_called_once()

        self.push.reset_mock()
        self.goals_db.write_text("not a sqlite database")
        self.run_event()
        self.push.assert_called_once()

    def test_opt_in_env_keeps_goal_continuation_notifications(self):
        self.write_goal("active")
        with patch.dict(os.environ, {"CODEX_NOTIFY_GOAL_CONTINUATION": "true"}):
            self.run_event()
        self.push.assert_called_once()

    def test_permission_request_during_active_goal_still_notifies(self):
        self.write_goal("active")
        self.run_event(event_type="permission-request")
        self.push.assert_called_once()

    def test_default_goals_db_uses_newest_schema_version(self):
        codex_home = self.tmp / ".codex"
        codex_home.mkdir()
        for name in ("goals_1.sqlite", "goals_2.sqlite", "goals_10.sqlite"):
            (codex_home / name).touch()
        with patch.dict(os.environ, {"CODEX_NOTIFY_GOALS_DB": ""}), \
                patch.object(notify.Path, "home", return_value=self.tmp):
            self.assertEqual(notify._goals_db_path(), codex_home / "goals_10.sqlite")


if __name__ == "__main__":
    unittest.main()
