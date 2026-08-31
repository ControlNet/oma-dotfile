import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import OmpGotifyNotify from "../omp-gotify-notify.js";

const MANAGED_ENV = [
	"GOTIFY_URL",
	"GOTIFY_TOKEN_FOR_OMP",
	"GOTIFY_TOKEN_FOR_OPENCODE",
	"GOTIFY_TOKEN_FOR_CODEX",
	"GOTIFY_NOTIFY_SUMMARIZER_MODEL",
	"GOTIFY_NOTIFY_SUMMARIZER_ENDPOINT",
	"GOTIFY_NOTIFY_SUMMARIZER_API_KEY",
	"OMP_NOTIFY_LOG_FILE",
];

function resetEnv() {
	for (const name of MANAGED_ENV) delete process.env[name];
}

function createHarness(fetchImpl) {
	const handlers = new Map();
	const calls = [];
	global.fetch = async (url, options) => {
		calls.push({ url: String(url), options });
		return fetchImpl?.(url, options) ?? { ok: true, status: 200 };
	};
	const pi = {
		on(name, handler) {
			handlers.set(name, handler);
		},
	};
	OmpGotifyNotify(pi);
	return { handlers, calls };
}

function context() {
	return {
		cwd: "/workspace/example",
		sessionManager: {
			getSessionId: () => "session-1",
		},
	};
}

function assistant(stopReason, text = "Done", errorMessage = "") {
	return {
		role: "assistant",
		stopReason,
		errorMessage,
		content: text ? [{ type: "text", text }] : [],
	};
}

function enableGotify() {
	process.env.GOTIFY_URL = "https://gotify.invalid";
	process.env.GOTIFY_TOKEN_FOR_OMP = "test-token";
}

async function runAgentEnd(harness, event) {
	await harness.handlers.get("agent_end")(event, context());
}

test.beforeEach(() => {
	resetEnv();
});

test.afterEach(() => {
	resetEnv();
	delete global.fetch;
});

test("skips agent_end when OMP has scheduled a continuation", async () => {
	enableGotify();
	const harness = createHarness();
	await runAgentEnd(harness, { willContinue: true, messages: [assistant("error")] });
	assert.equal(harness.calls.length, 0);
});

test("skips aborted terminal turns", async () => {
	enableGotify();
	const harness = createHarness();
	await runAgentEnd(harness, { messages: [assistant("aborted")] });
	assert.equal(harness.calls.length, 0);
});

test("sends one plain-text completion notification", async () => {
	enableGotify();
	const harness = createHarness();
	await runAgentEnd(harness, { messages: [assistant("end_turn", "Finished *cleanly*.")] });
	assert.equal(harness.calls.length, 1);
	const payload = JSON.parse(harness.calls[0].options.body);
	assert.equal(payload.message, "✅ Finished *cleanly*.");
});

test("sends one terminal error notification with bounded detail", async () => {
	enableGotify();
	const harness = createHarness();
	await runAgentEnd(harness, { messages: [assistant("error", "", "provider unavailable")] });
	assert.equal(harness.calls.length, 1);
	const payload = JSON.parse(harness.calls[0].options.body);
	assert.equal(payload.message, "❌ Agent turn failed: provider unavailable");
});

test("does not subscribe to auto_retry_end or tool_call", () => {
	enableGotify();
	const harness = createHarness();
	assert.equal(harness.handlers.has("auto_retry_end"), false);
	assert.equal(harness.handlers.has("tool_call"), false);
});

test("retry failure followed by terminal error produces one notification", async () => {
	enableGotify();
	const harness = createHarness();
	assert.equal(harness.handlers.has("auto_retry_end"), false);
	await runAgentEnd(harness, { messages: [assistant("error", "", "retry exhausted")] });
	assert.equal(harness.calls.length, 1);
});

test("notifies when ask execution starts", async () => {
	enableGotify();
	const harness = createHarness();
	await harness.handlers.get("tool_execution_start")(
		{ toolName: "ask", toolCallId: "ask-1", args: { questions: [{ question: "Proceed?" }] } },
		context(),
	);
	assert.equal(harness.calls.length, 1);
	const payload = JSON.parse(harness.calls[0].options.body);
	assert.equal(payload.message, "❓ Proceed?");
});

test("deduplicates repeated ask execution by toolCallId", async () => {
	enableGotify();
	const harness = createHarness();
	const event = { toolName: "ask", toolCallId: "ask-1", args: { questions: [{ question: "Proceed?" }] } };
	await harness.handlers.get("tool_execution_start")(event, context());
	await harness.handlers.get("tool_execution_start")(event, context());
	assert.equal(harness.calls.length, 1);
});

test("logs Gotify HTTP failures without throwing or leaking request data", async () => {
	const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "omp-notifier-test-"));
	try {
		const logFile = path.join(tempDir, "gotify.log");
		process.env.OMP_NOTIFY_LOG_FILE = logFile;
		enableGotify();
		const harness = createHarness(() => ({ ok: false, status: 503 }));
		await runAgentEnd(harness, { messages: [assistant("end_turn")] });
		const log = fs.readFileSync(logFile, "utf8");
		assert.match(log, /gotify HTTP 503/);
		assert.doesNotMatch(log, /test-token|gotify\.invalid|Done/);
	} finally {
		fs.rmSync(tempDir, { recursive: true, force: true });
	}
});

test("does not call fetch or summarizer when Gotify is not configured", async () => {
	process.env.GOTIFY_NOTIFY_SUMMARIZER_MODEL = "test-model";
	process.env.GOTIFY_NOTIFY_SUMMARIZER_ENDPOINT = "https://summarizer.invalid/v1";
	process.env.GOTIFY_NOTIFY_SUMMARIZER_API_KEY = "test-api-key";
	const harness = createHarness();
	await runAgentEnd(harness, { messages: [assistant("end_turn")] });
	assert.equal(harness.calls.length, 0);
});
