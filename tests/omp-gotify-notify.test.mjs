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
	"OMP_NOTIFY_COMPLETE",
	"OMP_NOTIFY_ERROR",
	"OMP_NOTIFY_QUESTION",
	"OMP_NOTIFY_DEDUP_WINDOW_SEC",
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

function context(branch = []) {
	return {
		cwd: "/workspace/example",
		agent: { kind: "main", id: "Main", name: "main", depth: 0 },
		sessionManager: {
			getSessionId: () => "session-1",
			getBranch: () => branch,
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

async function runAgentEnd(harness, event, ctx = context()) {
	await harness.handlers.get("agent_end")(event, ctx);
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

test("a failed push does not suppress the same notification inside the dedup window", async () => {
	const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "omp-notifier-test-"));
	try {
		process.env.OMP_NOTIFY_LOG_FILE = path.join(tempDir, "gotify.log");
		enableGotify();
		// Gotify fails once with 503, then recovers.
		const statuses = [503, 200];
		const harness = createHarness(() => {
			const status = statuses.shift() ?? 200;
			return { ok: status < 400, status };
		});
		await runAgentEnd(harness, { messages: [assistant("end_turn")] });
		await runAgentEnd(harness, { messages: [assistant("end_turn")] });
		await runAgentEnd(harness, { messages: [assistant("end_turn")] });
		// The failed attempt is retried once; the delivered one is still deduplicated.
		assert.equal(harness.calls.length, 2);
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

function updateGoal(harness, ctx, status) {
	return harness.handlers.get("goal_updated")(
		{ type: "goal_updated", goal: { id: "goal-1", status } },
		ctx,
	);
}

for (const depth of [0, 1]) {
	test(`silences subagent completion, error and questions at depth ${depth}`, async () => {
		enableGotify();
		const harness = createHarness();
		const ctx = context();
		ctx.agent = { kind: "sub", id: "child", name: "task", depth, parentId: "Main" };
		await runAgentEnd(harness, { messages: [assistant("stop")] }, ctx);
		await runAgentEnd(harness, { messages: [assistant("error", "", "child failed")] }, ctx);
		await harness.handlers.get("tool_execution_start")(
			{ toolName: "ask", toolCallId: "child-ask", args: { questions: [{ question: "Child input?" }] } },
			ctx,
		);
		assert.equal(harness.calls.length, 0);
		await runAgentEnd(harness, { messages: [assistant("stop", "Parent finished")] });
		assert.equal(harness.calls.length, 1);
		assert.match(JSON.parse(harness.calls[0].options.body).message, /Parent finished/);
	});
}

test("suppresses goal progress until completion and terminal settlement", async () => {
	enableGotify();
	const harness = createHarness();
	const ctx = context();
	await harness.handlers.get("agent_start")({}, ctx);
	await updateGoal(harness, ctx, "active");
	await runAgentEnd(harness, { messages: [assistant("stop", "First step")] }, ctx);
	await updateGoal(harness, ctx, "budget-limited");
	await runAgentEnd(harness, { messages: [] }, ctx);
	await updateGoal(harness, ctx, "complete");
	assert.equal(harness.calls.length, 0);
	await runAgentEnd(harness, { willContinue: true, messages: [assistant("stop", "Still unwinding")] }, ctx);
	assert.equal(harness.calls.length, 0);
	// The TUI clears the persisted mode before the extension receives agent_end.
	ctx.sessionManager.getBranch().push({ type: "mode_change", mode: "none" });
	await runAgentEnd(harness, { messages: [assistant("stop", "Goal finished")] }, ctx);
	assert.equal(harness.calls.length, 1);
	assert.match(JSON.parse(harness.calls[0].options.body).message, /Goal finished/);
});

for (const lifecycle of ["session_start", "session_switch", "session_branch", "session_tree", "agent_start"]) {
	test(`restores active goal suppression on ${lifecycle}`, async () => {
		enableGotify();
		const harness = createHarness();
		const ctx = context([
			{ type: "mode_change", mode: "none" },
			{ type: "mode_change", mode: "goal", data: { goal: { id: "restored", status: "active" } } },
			{ type: "message", message: assistant("stop", "Old progress") },
		]);
		await harness.handlers.get(lifecycle)({}, ctx);
		await runAgentEnd(harness, { messages: [assistant("stop", "More progress")] }, ctx);
		assert.equal(harness.calls.length, 0);
		await updateGoal(harness, ctx, "complete");
		await runAgentEnd(harness, { messages: [assistant("stop", "Restored goal finished")] }, ctx);
		assert.equal(harness.calls.length, 1);
		assert.match(JSON.parse(harness.calls[0].options.body).message, /Restored goal finished/);
	});
}

test("goal mode retains main-agent question and terminal error notifications", async () => {
	enableGotify();
	const harness = createHarness();
	const ctx = context();
	await updateGoal(harness, ctx, "active");
	await harness.handlers.get("tool_execution_start")(
		{ toolName: "ask", toolCallId: "goal-ask", args: { questions: [{ question: "Need credentials?" }] } },
		ctx,
	);
	await runAgentEnd(harness, { messages: [assistant("error", "", "provider unavailable")] }, ctx);
	assert.deepEqual(harness.calls.map(call => JSON.parse(call.options.body).message), [
		"❓ Need credentials?",
		"❌ Agent turn failed: provider unavailable",
	]);
});

for (const status of ["paused", "dropped"]) {
	test(`${status} goals do not report success or silence subsequent ordinary turns`, async () => {
		enableGotify();
		const harness = createHarness();
		const branch = [];
		const ctx = context(branch);
		await updateGoal(harness, ctx, "active");
		await updateGoal(harness, ctx, status);
		branch.push({
			type: "mode_change",
			mode: status === "paused" ? "goal_paused" : "none",
			data: { goal: { id: "goal-1", status } },
		});
		await runAgentEnd(harness, { messages: [assistant("stop", "Goal stopped")] }, ctx);
		assert.equal(harness.calls.length, 0);
		await harness.handlers.get("agent_start")({}, ctx);
		await runAgentEnd(harness, { messages: [assistant("stop", "Unrelated work finished")] }, ctx);
		assert.equal(harness.calls.length, 1);
		assert.match(JSON.parse(harness.calls[0].options.body).message, /Unrelated work finished/);
	});
}

test("switching away from a goal clears suppression and ignores older goal entries", async () => {
	enableGotify();
	const harness = createHarness();
	await updateGoal(harness, context(), "active");
	const ctx = context([
		{ type: "mode_change", mode: "goal", data: { goal: { id: "old-goal", status: "active" } } },
		{ type: "mode_change", mode: "none" },
	]);
	await harness.handlers.get("session_switch")({}, ctx);
	await runAgentEnd(harness, { messages: [assistant("stop", "New session finished")] }, ctx);
	assert.equal(harness.calls.length, 1);
	assert.match(JSON.parse(harness.calls[0].options.body).message, /New session finished/);
});

test("subagent goal events cannot change the main agent's notification state", async () => {
	enableGotify();
	const harness = createHarness();
	const main = context();
	const child = context();
	child.agent = { kind: "sub", id: "child", name: "task", depth: 1, parentId: "Main" };
	await updateGoal(harness, main, "active");
	await updateGoal(harness, child, "complete");
	await harness.handlers.get("agent_start")({}, child);
	await runAgentEnd(harness, { messages: [assistant("stop", "Main still working")] }, main);
	assert.equal(harness.calls.length, 0);
	await updateGoal(harness, main, "complete");
	await updateGoal(harness, child, "active");
	await runAgentEnd(harness, { messages: [assistant("stop", "Main goal finished")] }, main);
	assert.equal(harness.calls.length, 1);
	assert.match(JSON.parse(harness.calls[0].options.body).message, /Main goal finished/);
});

test("a subsequent goal completion cannot turn an earlier progress stop into a notification", async () => {
	enableGotify();
	const harness = createHarness();
	const ctx = context();
	await updateGoal(harness, ctx, "active");
	const progress = runAgentEnd(harness, { messages: [assistant("stop", "Intermediate progress")] }, ctx);
	await updateGoal(harness, ctx, "complete");
	await progress;
	assert.equal(harness.calls.length, 0);
	await runAgentEnd(harness, { messages: [assistant("stop", "Actual final result")] }, ctx);
	assert.equal(harness.calls.length, 1);
	assert.match(JSON.parse(harness.calls[0].options.body).message, /Actual final result/);
});
