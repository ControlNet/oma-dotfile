import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

// omp-wakatime-sync.js
//
// oh-my-pi extension that triggers WakaTime AI activity sync for OMP sessions.
//
// wakatime-cli (v2.24.0+) parses ~/.omp/agent/sessions natively, but only when it
// runs. Other WakaTime plugins run it as a side effect; on a host that only uses
// OMP nothing would. This extension runs `wakatime-cli --sync-ai-activity` in the
// background after completed agent runs (rate limited) and on session shutdown.
// wakatime-cli holds its own sync lock, so overlapping runs are skipped by the CLI.
// It never downloads wakatime-cli and never sends heartbeats itself.
//
// Install path (auto-discovered by omp):
//   ~/.omp/agent/extensions/omp-wakatime-sync.js
//
// Optional env:
//   OMP_WAKATIME_SYNC                default true; false disables the extension
//   OMP_WAKATIME_SYNC_INTERVAL_SEC   default 120; minimum seconds between agent_end syncs
//   OMP_WAKATIME_CLI                 explicit wakatime-cli path
//   OMP_WAKATIME_LOG_FILE            default ~/.omp/logs/wakatime-sync.log
//   WAKATIME_HOME                    also searched for <WAKATIME_HOME>/.wakatime/wakatime-cli*

const DEFAULT_INTERVAL_SEC = 120;
const MAX_LOG_BYTES = 256 * 1024;

function env(name, fallback = "") {
	return String(process.env[name] ?? fallback).trim();
}

function envBool(name, fallback) {
	const raw = env(name);
	if (!raw) return fallback;
	const normalized = raw.toLowerCase();
	return normalized === "1" || normalized === "true" || normalized === "yes" || normalized === "on";
}

function envInt(name, fallback) {
	const parsed = Number.parseInt(env(name), 10);
	return Number.isFinite(parsed) ? parsed : fallback;
}

function logFilePath() {
	return env("OMP_WAKATIME_LOG_FILE", path.join(os.homedir(), ".omp", "logs", "wakatime-sync.log"));
}

function logDiagnostic(stage, detail) {
	try {
		const file = logFilePath();
		fs.mkdirSync(path.dirname(file), { recursive: true });
		if (fs.existsSync(file) && fs.statSync(file).size >= MAX_LOG_BYTES) {
			fs.renameSync(file, `${file}.1`);
		}
		const safeDetail = String(detail).replace(/\s+/g, " ").slice(0, 200);
		fs.appendFileSync(file, `${new Date().toISOString()} ${stage} ${safeDetail}\n`, "utf8");
	} catch {
		// Logging must never affect the host runtime.
	}
}

const isWindows = process.platform === "win32";
const binaryName = isWindows ? "wakatime-cli.exe" : "wakatime-cli";

// Matches the release asset names that WakaTime plugins install, e.g. wakatime-cli-linux-amd64.
function platformBinaryName() {
	const osName = isWindows ? "windows" : process.platform;
	const arch = { x64: "amd64", ia32: "386", arm64: "arm64", arm: "arm" }[process.arch] ?? process.arch;
	return `wakatime-cli-${osName}-${arch}${isWindows ? ".exe" : ""}`;
}

export function cliCandidates() {
	const resourceDirs = [];
	const wakatimeHome = env("WAKATIME_HOME");
	if (wakatimeHome) resourceDirs.push(path.join(wakatimeHome, ".wakatime"));
	resourceDirs.push(path.join(os.homedir(), ".wakatime"));

	const candidates = [];
	for (const dir of resourceDirs) {
		candidates.push(path.join(dir, binaryName), path.join(dir, platformBinaryName()));
	}
	for (const dir of env("PATH").split(path.delimiter)) {
		if (dir) candidates.push(path.join(dir, binaryName));
	}
	return candidates;
}
cliCandidates.platformBinaryName = platformBinaryName;

function resolveCli() {
	const explicit = env("OMP_WAKATIME_CLI");
	if (explicit) return explicit;
	return cliCandidates().find((file) => {
		try {
			return fs.statSync(file).isFile();
		} catch {
			return false;
		}
	});
}

export default function OmpWakatimeSync(pi) {
	if (!envBool("OMP_WAKATIME_SYNC", true)) return;

	const intervalMs = Math.max(0, envInt("OMP_WAKATIME_SYNC_INTERVAL_SEC", DEFAULT_INTERVAL_SEC)) * 1000;
	let lastSyncAt = Number.NEGATIVE_INFINITY;
	let reportedMissingCli = false;

	function sync(reason, force) {
		try {
			const now = Date.now();
			if (!force && now - lastSyncAt < intervalMs) return;

			const cli = resolveCli();
			if (!cli) {
				if (!reportedMissingCli) logDiagnostic("sync_skip", "no_cli");
				reportedMissingCli = true;
				return;
			}

			lastSyncAt = now;
			logDiagnostic("sync_spawn", `reason=${reason} cli=${cli}`);
			const child = spawn(cli, ["--sync-ai-activity"], {
				detached: true,
				stdio: "ignore",
				windowsHide: true,
			});
			child.on("error", (error) => logDiagnostic("sync_error", `${error?.code || error?.name || "Error"} cli=${cli}`));
			child.unref();
		} catch (error) {
			logDiagnostic("sync_error", error?.code || error?.name || "Error");
		}
	}

	pi.on("agent_end", async (event) => {
		if (event?.willContinue) return;
		sync("agent_end", false);
	});

	pi.on("session_shutdown", async () => {
		sync("session_shutdown", true);
	});
}
