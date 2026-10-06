import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import OmpWakatimeSync, { cliCandidates } from "../omp-wakatime-sync.js";

// Synthetic test double: a shell script stands in for wakatime-cli and records its
// arguments. No real wakatime-cli is executed and nothing is sent anywhere.

const MANAGED_ENV = [
	"HOME",
	"PATH",
	"WAKATIME_HOME",
	"OMP_WAKATIME_SYNC",
	"OMP_WAKATIME_SYNC_INTERVAL_SEC",
	"OMP_WAKATIME_CLI",
	"OMP_WAKATIME_LOG_FILE",
];
const savedEnv = Object.fromEntries(MANAGED_ENV.map((name) => [name, process.env[name]]));

function restoreEnv() {
	for (const [name, value] of Object.entries(savedEnv)) {
		if (value === undefined) delete process.env[name];
		else process.env[name] = value;
	}
}

function setup(t) {
	const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "omp-wakatime-sync-"));
	t.after(() => {
		restoreEnv();
		fs.rmSync(tmp, { recursive: true, force: true });
	});
	for (const name of MANAGED_ENV) delete process.env[name];
	process.env.HOME = path.join(tmp, "home");
	process.env.PATH = path.join(tmp, "empty-bin");
	process.env.OMP_WAKATIME_LOG_FILE = path.join(tmp, "sync.log");
	fs.mkdirSync(process.env.HOME, { recursive: true });
	return tmp;
}

function fakeCli(file, argsOut) {
	fs.mkdirSync(path.dirname(file), { recursive: true });
	fs.writeFileSync(file, `#!/bin/sh\necho "$@" >> "${argsOut}"\n`, { mode: 0o755 });
	return file;
}

function load() {
	const handlers = new Map();
	OmpWakatimeSync({ on: (name, handler) => handlers.set(name, handler) });
	return handlers;
}

function logLines() {
	const file = process.env.OMP_WAKATIME_LOG_FILE;
	return fs.existsSync(file) ? fs.readFileSync(file, "utf8").trim().split("\n") : [];
}

function spawnCount() {
	return logLines().filter((line) => line.includes(" sync_spawn ")).length;
}

async function waitForFile(file, timeoutMs = 3000) {
	const deadline = Date.now() + timeoutMs;
	while (Date.now() < deadline) {
		if (fs.existsSync(file) && fs.readFileSync(file, "utf8").trim()) return;
		await new Promise((resolve) => setTimeout(resolve, 25));
	}
	assert.fail(`timed out waiting for ${file}`);
}

test("completed agent run starts a detached wakatime-cli AI sync", async (t) => {
	const tmp = setup(t);
	const argsOut = path.join(tmp, "args.txt");
	process.env.OMP_WAKATIME_CLI = fakeCli(path.join(tmp, "bin", "wakatime-cli"), argsOut);

	await load().get("agent_end")({ willContinue: false }, {});

	await waitForFile(argsOut);
	assert.equal(fs.readFileSync(argsOut, "utf8").trim(), "--sync-ai-activity");
	assert.equal(spawnCount(), 1);
});

test("agent_end that will continue does not sync", async (t) => {
	const tmp = setup(t);
	process.env.OMP_WAKATIME_CLI = fakeCli(path.join(tmp, "bin", "wakatime-cli"), path.join(tmp, "a"));

	await load().get("agent_end")({ willContinue: true }, {});

	assert.equal(spawnCount(), 0);
});

test("agent_end syncs are rate limited by the configured interval", async (t) => {
	const tmp = setup(t);
	process.env.OMP_WAKATIME_CLI = fakeCli(path.join(tmp, "bin", "wakatime-cli"), path.join(tmp, "a"));

	const handlers = load();
	await handlers.get("agent_end")({}, {});
	await handlers.get("agent_end")({}, {});
	assert.equal(spawnCount(), 1);

	process.env.OMP_WAKATIME_SYNC_INTERVAL_SEC = "0";
	const unlimited = load();
	await unlimited.get("agent_end")({}, {});
	await unlimited.get("agent_end")({}, {});
	assert.equal(spawnCount(), 3);
});

test("session_shutdown always syncs, even inside the interval", async (t) => {
	const tmp = setup(t);
	process.env.OMP_WAKATIME_CLI = fakeCli(path.join(tmp, "bin", "wakatime-cli"), path.join(tmp, "a"));

	const handlers = load();
	await handlers.get("agent_end")({}, {});
	await handlers.get("session_shutdown")({}, {});

	assert.equal(spawnCount(), 2);
});

test("OMP_WAKATIME_SYNC=false disables the extension", async (t) => {
	const tmp = setup(t);
	process.env.OMP_WAKATIME_CLI = fakeCli(path.join(tmp, "bin", "wakatime-cli"), path.join(tmp, "a"));
	process.env.OMP_WAKATIME_SYNC = "false";

	const handlers = load();
	assert.equal(handlers.size, 0);
	assert.equal(spawnCount(), 0);
});

test("missing wakatime-cli is logged once and never throws", async (t) => {
	setup(t);

	const handlers = load();
	await handlers.get("agent_end")({}, {});
	await handlers.get("session_shutdown")({}, {});

	assert.equal(spawnCount(), 0);
	assert.equal(logLines().filter((line) => line.includes(" sync_skip no_cli")).length, 1);
});

test("unexecutable cli path is logged without throwing", async (t) => {
	const tmp = setup(t);
	const notExecutable = path.join(tmp, "bin", "wakatime-cli");
	fs.mkdirSync(path.dirname(notExecutable), { recursive: true });
	fs.writeFileSync(notExecutable, "not a program\n", { mode: 0o644 });
	process.env.OMP_WAKATIME_CLI = notExecutable;

	await load().get("session_shutdown")({}, {});
	await new Promise((resolve) => setTimeout(resolve, 200));

	assert.ok(logLines().some((line) => line.includes(" sync_error ")));
});

test("cli lookup prefers the WakaTime resources dir, then PATH", (t) => {
	const tmp = setup(t);
	const home = process.env.HOME;
	const wakatimeHome = path.join(tmp, "waka-home");
	const pathBin = path.join(tmp, "path-bin");
	process.env.WAKATIME_HOME = wakatimeHome;
	process.env.PATH = pathBin;

	const candidates = cliCandidates();
	const platformName = cliCandidates.platformBinaryName();
	assert.deepEqual(candidates, [
		path.join(wakatimeHome, ".wakatime", "wakatime-cli"),
		path.join(wakatimeHome, ".wakatime", platformName),
		path.join(home, ".wakatime", "wakatime-cli"),
		path.join(home, ".wakatime", platformName),
		path.join(pathBin, process.platform === "win32" ? "wakatime-cli.exe" : "wakatime-cli"),
	]);
});

test("cli found under ~/.wakatime is used without any override", async (t) => {
	const tmp = setup(t);
	const argsOut = path.join(tmp, "args.txt");
	fakeCli(path.join(process.env.HOME, ".wakatime", cliCandidates.platformBinaryName()), argsOut);

	await load().get("session_shutdown")({}, {});

	await waitForFile(argsOut);
	assert.equal(spawnCount(), 1);
});
