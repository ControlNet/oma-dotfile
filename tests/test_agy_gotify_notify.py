"""Synthetic agy Stop payloads and transcripts; Gotify is mocked or a local stand-in."""

import http.server
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import patch
from support import TestCase

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "config" / "agy" / "plugins" / "oma-dotfile" / "scripts" / "gotify-notify.py"
SPEC = importlib.util.spec_from_file_location("agy_notify", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
notify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(notify)

TOKEN = "synthetic-test-only-not-a-credential"


def row(step, source, kind, **fields):
    return {"step_index": step, "source": source, "type": kind, "status": "DONE", **fields}


def write_transcript(directory: Path, rows, full_rows=None) -> Path:
    """agy's transcript.jsonl, and transcript_full.jsonl beside it when full_rows is given."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "transcript.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    if full_rows is not None:
        (directory / "transcript_full.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in full_rows), encoding="utf-8")
    return path


class NotifierTestCase(TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.dict(os.environ, {
            "PLUGIN_DATA": str(self.tmp / "data"),
            "GOTIFY_URL": "https://gotify.invalid",
            "GOTIFY_TOKEN_FOR_AGY": TOKEN,
        }, clear=True))
        self.transcript = write_transcript(self.tmp / "logs", [
            row(0, "USER_EXPLICIT", "USER_INPUT", content="<USER_REQUEST>\nFix it\n</USER_REQUEST>"),
            row(1, "MODEL", "PLANNER_RESPONSE", tool_calls=[{"name": "view_file", "args": {}}]),
            row(2, "MODEL", "GENERIC", content="file contents"),
            row(3, "MODEL", "PLANNER_RESPONSE", content="Fixed the failing test."),
        ])

    def stop(self, **fields):
        return {
            "hookEventName": "Stop", "conversationId": "synthetic-conversation",
            "terminationReason": "NO_TOOL_CALL", "fullyIdle": True, "continuationActive": False,
            "error": "", "cwd": "/work/project", "workspacePaths": ["/work/project"],
            "transcriptPath": str(self.transcript), **fields,
        }


class EventTests(NotifierTestCase):
    def test_a_finished_turn_sends_the_last_response(self):
        self.assertEqual(notify.event_message(self.stop()),
                         ("Response finished: Fixed the failing test.", "Fixed the failing test."))

    def test_the_untruncated_transcript_is_preferred(self):
        # transcript.jsonl cuts long contents; transcript_full.jsonl beside it keeps them.
        long = "x" * 5000
        write_transcript(self.transcript.parent, [
            row(0, "USER_EXPLICIT", "USER_INPUT", content="go"),
            row(1, "MODEL", "PLANNER_RESPONSE", content="cut", truncated_fields=["content"]),
        ], full_rows=[
            row(0, "USER_EXPLICIT", "USER_INPUT", content="go"),
            row(1, "MODEL", "PLANNER_RESPONSE", content=long),
        ])
        self.assertEqual(notify.event_message(self.stop())[1], long)

    def test_a_response_from_an_earlier_turn_is_not_reported(self):
        write_transcript(self.transcript.parent, [
            row(0, "USER_EXPLICIT", "USER_INPUT", content="first"),
            row(1, "MODEL", "PLANNER_RESPONSE", content="First answer."),
            row(2, "USER_EXPLICIT", "USER_INPUT", content="second"),
            row(3, "MODEL", "PLANNER_RESPONSE", content=""),
        ])
        self.assertIsNone(notify.event_message(self.stop()))

    def test_errors_and_early_stops_are_reported(self):
        self.assertEqual(notify.event_message(self.stop(terminationReason="ERROR", error="quota exceeded")),
                         ("Error: quota exceeded", ""))
        self.assertEqual(notify.event_message(self.stop(terminationReason="MAX_INVOCATIONS")),
                         ("Stopped: MAX_INVOCATIONS", ""))

    def test_what_needs_no_attention_is_ignored(self):
        for payload in (
            self.stop(terminationReason="USER_CANCELED"),
            self.stop(fullyIdle=False),  # background work is still running
            self.stop(hookEventName="PreInvocation"),
            self.stop(transcriptPath=str(self.tmp / "missing.jsonl")),
            self.stop(transcriptPath=None),
        ):
            with self.subTest(payload=payload):
                self.assertIsNone(notify.event_message(payload))

    def test_toggles(self):
        with patch.dict(os.environ, {"AGY_NOTIFY_COMPLETE": "0", "AGY_NOTIFY_ERROR": "false"}):
            self.assertIsNone(notify.event_message(self.stop()))
            self.assertIsNone(notify.event_message(self.stop(terminationReason="ERROR")))

    def test_the_title_names_the_workspace_not_the_hook_dir(self):
        # agy runs hooks in the plugin dir; the payload names where the agent works.
        self.assertTrue(notify.title(self.stop()).startswith("Antigravity CLI :: project@"))
        self.assertTrue(notify.title(self.stop(cwd="")).startswith("Antigravity CLI :: project@"))
        with patch.dict(os.environ, {"AGY_NOTIFY_TITLE": "mine"}):
            self.assertEqual(notify.title(self.stop()), "mine")

    def test_a_large_transcript_is_read_from_its_end(self):
        filler = [row(i, "MODEL", "GENERIC", content="y" * 1000) for i in range(1, 3000)]
        write_transcript(self.transcript.parent, [
            row(0, "USER_EXPLICIT", "USER_INPUT", content="go"), *filler,
            row(3000, "MODEL", "PLANNER_RESPONSE", content="Done."),
        ])
        self.assertEqual(notify.event_message(self.stop())[1], "Done.")


class HookTests(NotifierTestCase):
    def run_hook(self, stdin: bytes, *args):
        out = io.StringIO()
        with patch.object(sys, "stdin", io.TextIOWrapper(io.BytesIO(stdin), encoding="utf-8")), \
             patch.object(sys, "stdout", out):
            self.assertEqual(notify.main(list(args)), 0)
        return out.getvalue()

    def test_the_hook_answers_at_once_and_leaves_delivery_to_a_worker(self):
        raw = json.dumps(self.stop()).encode()
        with patch.object(notify, "spawn_worker") as spawn, patch.object(notify, "post_json") as post:
            self.assertEqual(self.run_hook(raw), "{}\n")
        spawn.assert_called_once_with(raw)
        post.assert_not_called()

    def test_nothing_is_spawned_when_nothing_would_be_sent(self):
        for raw, env in ((json.dumps(self.stop(terminationReason="USER_CANCELED")).encode(), {}),
                         (json.dumps(self.stop()).encode(), {"GOTIFY_URL": ""}),
                         (b"not json", {}), (b"[]", {})):
            with self.subTest(raw=raw, env=env), patch.dict(os.environ, env), \
                 patch.object(notify, "spawn_worker") as spawn:
                # Never anything but {}: agy would act on a "decision" such as "continue".
                self.assertEqual(self.run_hook(raw), "{}\n")
                spawn.assert_not_called()

    def test_the_worker_posts_the_message(self):
        with patch.object(notify, "post_json", return_value={}) as post:
            self.run_hook(json.dumps(self.stop()).encode(), "--worker")
        url, body, headers = post.call_args.args[:3]
        self.assertEqual(url, "https://gotify.invalid/message")
        self.assertEqual(body["message"], "Response finished: Fixed the failing test.")
        self.assertTrue(body["title"].startswith("Antigravity CLI :: project@"))
        self.assertEqual(headers["X-Gotify-Key"], TOKEN)

    def test_the_worker_uses_a_summary_when_configured(self):
        summarizer = {"GOTIFY_NOTIFY_SUMMARIZER_MODEL": "m", "GOTIFY_NOTIFY_SUMMARIZER_ENDPOINT": "https://s.invalid/v1",
                      "GOTIFY_NOTIFY_SUMMARIZER_API_KEY": "synthetic"}
        replies = [{"choices": [{"message": {"content": "Test fixed."}}]}, {}]
        with patch.dict(os.environ, summarizer), patch.object(notify, "post_json", side_effect=replies) as post:
            self.run_hook(json.dumps(self.stop()).encode(), "--worker")
        self.assertEqual(post.call_args.args[1]["message"], "Response finished: Test fixed.")

    def test_the_token_falls_back_to_opencodes(self):
        with patch.dict(os.environ, {"GOTIFY_TOKEN_FOR_AGY": "", "GOTIFY_TOKEN_FOR_OPENCODE": "fallback"}), \
             patch.object(notify, "post_json", return_value={}) as post:
            self.run_hook(json.dumps(self.stop()).encode(), "--worker")
        self.assertEqual(post.call_args.args[2]["X-Gotify-Key"], "fallback")


class GotifyStandIn(http.server.ThreadingHTTPServer):
    def __init__(self):
        self.bodies: list[dict[str, object]] = []
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                server.bodies.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(200)
                self.end_headers()
                _ = self.wfile.write(b"{}")

            def log_message(self, format, *args):
                pass

        super().__init__(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.serve_forever, daemon=True).start()


class DetachedDeliveryTests(NotifierTestCase):
    def test_the_hook_exits_before_the_message_is_delivered(self):
        # A real process tree: the hook returns, the detached worker still posts.
        gotify = GotifyStandIn()
        self.addCleanup(gotify.server_close)
        self.addCleanup(gotify.shutdown)  # cleanups run last in, first out
        env = {**os.environ, "GOTIFY_URL": f"http://127.0.0.1:{gotify.server_address[1]}",
               "SYSTEMROOT": os.environ.get("SYSTEMROOT", r"C:\Windows")}
        result = subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps(self.stop()).encode(),
                                capture_output=True, env=env, timeout=30, check=False)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, b"{}"), result.stderr)
        deadline = time.monotonic() + 30
        while not gotify.bodies and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertEqual([body["message"] for body in gotify.bodies], ["Response finished: Fixed the failing test."])
