// Mocked fetch and OpenCode client only; no notification leaves the machine.
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

// Module constants read the environment at import, so set it first.
const home = fs.mkdtempSync(path.join(os.tmpdir(), "opencode-gotify-"));
process.env.HOME = home; // diagnostics go to ~/.local/share/opencode
process.env.GOTIFY_URL = "https://gotify.example.invalid";
process.env.GOTIFY_TOKEN_FOR_OPENCODE = "test-only-fake-token";
process.env.OPENCODE_NOTIFY_IDLE_CONFIRM_MS = "0";
process.env.OPENCODE_NOTIFY_GOTIFY_TIMEOUT_SEC = "1";
for (const name of ["GOTIFY_NOTIFY_SUMMARIZER_MODEL", "GOTIFY_NOTIFY_SUMMARIZER_ENDPOINT",
	"GOTIFY_NOTIFY_SUMMARIZER_API_KEY", "OPENCODE_NOTIFY_PERMISSION", "OPENCODE_NOTIFY_COMPLETE"]) {
	delete process.env[name];
}
const { GotifyNotify } = await import("../plugins/gotify-notify.js");

test.after(() => fs.rmSync(home, { recursive: true, force: true }));

function fakeClient() {
	return {
		session: {
			get: async () => ({ data: {} }), // root session, no directory
			status: async () => ({ data: {} }),
			messages: async () => ({
				data: [{ info: { id: "msg-1", role: "assistant" }, parts: [{ type: "text", text: "All done" }] }],
			}),
		},
	};
}

function okFetch(sent) {
	return async (_url, options) => {
		sent.push(JSON.parse(options.body).message);
		return { ok: true, status: 200, statusText: "", text: async () => "" };
	};
}

async function waitFor(condition, timeoutMs = 2000) {
	const deadline = Date.now() + timeoutMs;
	while (!condition()) {
		if (Date.now() > deadline) throw new Error("condition not met in time");
		await new Promise((resolve) => setTimeout(resolve, 5));
	}
}

test("a Gotify server that never answers does not block the permission hook", async () => {
	// Given a server that accepts the request and never responds.
	const signals = [];
	global.fetch = (_url, options) => new Promise((_resolve, reject) => {
		signals.push(options?.signal);
		options?.signal?.addEventListener("abort", () => reject(new Error("aborted")));
	});
	const hooks = await GotifyNotify({ client: fakeClient(), directory: home });

	// When a permission request is announced.
	const outcome = await Promise.race([
		hooks["permission.ask"]({ sessionID: "ses-1" }).then(() => "returned"),
		new Promise((resolve) => setTimeout(() => resolve("stuck"), 3000)),
	]);

	// Then the request was bounded by the 1 s timeout and the hook returned.
	assert.equal(outcome, "returned");
	assert.ok(signals[0], "fetch received an AbortSignal");
});

test("a failed completion push is retried on the next idle event", async () => {
	// Given Gotify fails once with 503, then recovers.
	const statuses = [503, 200];
	const sent = [];
	global.fetch = async (_url, options) => {
		sent.push(JSON.parse(options.body).message);
		const status = statuses.shift() ?? 200;
		return { ok: status < 400, status, statusText: "", text: async () => "" };
	};
	const hooks = await GotifyNotify({ client: fakeClient(), directory: home });
	const idle = { event: { type: "session.idle", properties: { sessionID: "ses-1" } } };

	// When the same finished message triggers idle three times.
	await hooks.event(idle);
	await waitFor(() => sent.length === 1);
	await hooks.event(idle);
	await waitFor(() => sent.length === 2);
	await hooks.event(idle);
	await new Promise((resolve) => setTimeout(resolve, 50));

	// Then the failed push is retried once, and the delivered one is not repeated.
	assert.deepEqual(sent, ["✅ All done", "✅ All done"]);
});

test("a turn that starts while a completion is being prepared cancels it", async () => {
	// Given a completion whose message lookup is still in flight.
	const sent = [];
	global.fetch = okFetch(sent);
	let releaseMessages;
	let lookups = 0;
	const client = fakeClient();
	const messages = client.session.messages;
	client.session.messages = async (...args) => {
		lookups += 1;
		await new Promise((resolve) => { releaseMessages = resolve; });
		return messages(...args);
	};
	const hooks = await GotifyNotify({ client, directory: home });
	await hooks.event({ event: { type: "session.idle", properties: { sessionID: "ses-1" } } });
	await waitFor(() => lookups === 1);

	// When the next turn starts before the lookup returns.
	await hooks.event({ event: { type: "session.status", properties: { sessionID: "ses-1", status: { type: "busy" } } } });
	releaseMessages();
	await new Promise((resolve) => setTimeout(resolve, 50));

	// Then the previous turn's completion is not pushed.
	assert.deepEqual(sent, []);
});
