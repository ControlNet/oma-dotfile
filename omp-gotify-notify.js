// omp-gotify-notify.js
//
// oh-my-pi extension that sends Gotify notifications for key agent events.
//
// Install path (auto-discovered by omp):
//   ~/.omp/agent/extensions/omp-gotify-notify.js
//
// Required env:
//   GOTIFY_URL
//   GOTIFY_TOKEN_FOR_OMP (fallback: GOTIFY_TOKEN_FOR_OPENCODE, GOTIFY_TOKEN_FOR_CODEX)
//
// Optional:
//   OMP_NOTIFY_TITLE                  default "OMP"
//   OMP_NOTIFY_MAX_CHARS              default 280
//   OMP_NOTIFY_HEAD                   default 50
//   OMP_NOTIFY_TAIL                   default 50
//   OMP_NOTIFY_COMPLETE               default true
//   OMP_NOTIFY_ERROR                  default true
//   OMP_NOTIFY_QUESTION               default true
//   OMP_NOTIFY_DEDUP_WINDOW_SEC       default 15
//   GOTIFY_NOTIFY_SUMMARIZER_MODEL
//   GOTIFY_NOTIFY_SUMMARIZER_ENDPOINT
//   GOTIFY_NOTIFY_SUMMARIZER_API_KEY
//   OMP_NOTIFY_SUMMARIZER_TIMEOUT_SEC default 120
//   OMP_NOTIFY_SUMMARIZER_MAX_INPUT_CHARS default 5000

const DEFAULT_MAX_CHARS = 280;
const DEFAULT_HEAD = 50;
const DEFAULT_TAIL = 50;
const DEFAULT_DEDUP_WINDOW_SEC = 15;
const DEFAULT_SUMMARIZER_TIMEOUT_MS = 120_000;
const DEFAULT_SUMMARIZER_MAX_INPUT_CHARS = 5000;

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

function normalizeBase(url) {
	const value = String(url || "").trim();
	return value.endsWith("/") ? value.slice(0, -1) : value;
}

function normalizeText(value) {
	return String(value || "").replace(/\s+/g, " ").trim();
}

function truncate(text, limit) {
	if (limit <= 0 || text.length <= limit) return text;
	if (limit <= 3) return text.slice(0, limit);
	return `${text.slice(0, limit - 3)}...`;
}

function preview(text, head, tail) {
	const normalized = normalizeText(text);
	if (!normalized) return "";
	if (head < 0) head = 0;
	if (tail < 0) tail = 0;
	if (normalized.length <= head + tail + 3) return normalized;
	if (head === 0) return normalized.slice(-tail);
	if (tail === 0) return normalized.slice(0, head);
	return `${normalized.slice(0, head)}...${normalized.slice(-tail)}`;
}

function escapeMarkdown(text) {
	const escapeSet = new Set(["\\", "`", "*", "_", "~", "[", "]", "(", ")", "#", "+", "-", ".", "!", ">", "|", "{", "}"]);
	let out = "";
	for (const ch of String(text || "")) {
		out += escapeSet.has(ch) ? `\\${ch}` : ch;
	}
	return out;
}

function extractAssistantText(message) {
	if (!message || message.role !== "assistant" || !Array.isArray(message.content)) return "";
	const parts = [];
	for (const block of message.content) {
		if (block && block.type === "text" && typeof block.text === "string") {
			const text = normalizeText(block.text);
			if (text) parts.push(text);
		}
	}
	return normalizeText(parts.join(" "));
}

function extractAskQuestion(input) {
	if (!input || typeof input !== "object") return "";
	const questions = Array.isArray(input.questions) ? input.questions : [];
	if (questions.length === 0) return "";
	const first = questions[0];
	if (!first || typeof first !== "object") return "";
	return normalizeText(first.question || first.header || "");
}

function extractOpenAIText(payload) {
	if (!payload || typeof payload !== "object") return "";

	if (typeof payload.output_text === "string" && payload.output_text.trim()) {
		return normalizeText(payload.output_text);
	}

	if (Array.isArray(payload.output)) {
		for (const item of payload.output) {
			if (!item || typeof item !== "object" || !Array.isArray(item.content)) continue;
			for (const part of item.content) {
				if (part && typeof part.text === "string" && part.text.trim()) {
					return normalizeText(part.text);
				}
			}
		}
	}

	if (Array.isArray(payload.choices)) {
		for (const choice of payload.choices) {
			if (!choice || typeof choice !== "object") continue;
			const message = choice.message;
			if (message && typeof message === "object" && typeof message.content === "string" && message.content.trim()) {
				return normalizeText(message.content);
			}
		}
	}

	return "";
}

function endpointJoin(base, suffix) {
	if (!base) return "";
	return base.endsWith(suffix) ? base : `${base}${suffix}`;
}

async function postJSON(url, body, headers, timeoutMs) {
	const controller = new AbortController();
	const timeout = setTimeout(() => controller.abort(), timeoutMs);
	try {
		const res = await fetch(url, {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				...headers,
			},
			body: JSON.stringify(body),
			signal: controller.signal,
		});
		if (!res.ok) return null;
		const json = await res.json().catch(() => null);
		return json && typeof json === "object" ? json : null;
	} catch {
		return null;
	} finally {
		clearTimeout(timeout);
	}
}

function summarizerConfig() {
	const model = env("GOTIFY_NOTIFY_SUMMARIZER_MODEL");
	const endpoint = normalizeBase(env("GOTIFY_NOTIFY_SUMMARIZER_ENDPOINT"));
	const apiKey = env("GOTIFY_NOTIFY_SUMMARIZER_API_KEY");
	if (!model || !endpoint || !apiKey) return null;
	return { model, endpoint, apiKey };
}

async function summarizeWithLLM(text) {
	const config = summarizerConfig();
	if (!config) return "";

	const timeoutMs = Math.max(1, envInt("OMP_NOTIFY_SUMMARIZER_TIMEOUT_SEC", DEFAULT_SUMMARIZER_TIMEOUT_MS / 1000)) * 1000;
	const maxInputChars = Math.max(1, envInt("OMP_NOTIFY_SUMMARIZER_MAX_INPUT_CHARS", DEFAULT_SUMMARIZER_MAX_INPUT_CHARS));
	const clipped = truncate(normalizeText(text), maxInputChars);
	if (!clipped) return "";

	const prompt =
		"You are a concise summarizer. Output plain text only.\n" +
		"Use the same language as the input text.\n" +
		"Summarize this in ONE short sentence (max 80 chars). " +
		"No markdown, no quotes, just plain text:\n\n" +
		clipped;

	const headers = {
		Authorization: `Bearer ${config.apiKey}`,
		"api-key": config.apiKey,
	};

	const chatData = await postJSON(
		endpointJoin(config.endpoint, "/chat/completions"),
		{
			model: config.model,
			messages: [{ role: "user", content: prompt }],
			max_tokens: 80,
		},
		headers,
		timeoutMs,
	);
	if (chatData) {
		const out = extractOpenAIText(chatData);
		if (out) return truncate(out, 200);
	}

	const responsesData = await postJSON(
		endpointJoin(config.endpoint, "/responses"),
		{
			model: config.model,
			input: [{ role: "user", content: [{ type: "input_text", text: prompt }] }],
			reasoning: { effort: "low" },
			max_output_tokens: 80,
		},
		headers,
		timeoutMs,
	);
	if (!responsesData) return "";
	const out = extractOpenAIText(responsesData);
	return out ? truncate(out, 200) : "";
}

async function pushGotify(title, message) {
	const base = normalizeBase(env("GOTIFY_URL"));
	const token = env("GOTIFY_TOKEN_FOR_OMP") || env("GOTIFY_TOKEN_FOR_OPENCODE") || env("GOTIFY_TOKEN_FOR_CODEX");
	if (!base || !token || !message) return;

	try {
		await fetch(`${base}/message`, {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				"X-Gotify-Key": token,
			},
			body: JSON.stringify({
				title,
				message,
				priority: 5,
			}),
		});
	} catch {
		// Swallow errors; notifier must never break agent flow.
	}
}

export default function OmpGotifyNotify(pi) {
	const sentCache = new Map();

	const title = env("OMP_NOTIFY_TITLE", "OMP");
	const maxChars = Math.max(1, envInt("OMP_NOTIFY_MAX_CHARS", DEFAULT_MAX_CHARS));
	const head = Math.max(0, envInt("OMP_NOTIFY_HEAD", DEFAULT_HEAD));
	const tail = Math.max(0, envInt("OMP_NOTIFY_TAIL", DEFAULT_TAIL));
	const dedupWindowSec = Math.max(0, envInt("OMP_NOTIFY_DEDUP_WINDOW_SEC", DEFAULT_DEDUP_WINDOW_SEC));

	const notifyComplete = envBool("OMP_NOTIFY_COMPLETE", true);
	const notifyError = envBool("OMP_NOTIFY_ERROR", true);
	const notifyQuestion = envBool("OMP_NOTIFY_QUESTION", true);

	function shouldSend(sessionId, eventName, message) {
		if (dedupWindowSec <= 0) return true;
		const now = Math.floor(Date.now() / 1000);
		const key = `${sessionId}|${eventName}|${message}`;
		const last = sentCache.get(key);
		if (typeof last === "number" && now - last < dedupWindowSec) return false;

		sentCache.set(key, now);
		for (const [cacheKey, ts] of sentCache.entries()) {
			if (now - ts > dedupWindowSec) sentCache.delete(cacheKey);
		}
		return true;
	}

	async function send(sessionId, eventName, message, summarizeSource = "") {
		if (!message) return;
		if (!shouldSend(sessionId, eventName, message)) return;

		let finalMessage = message;
		if (summarizeSource) {
			const summary = await summarizeWithLLM(summarizeSource);
			if (summary) {
				finalMessage = `✅ ${escapeMarkdown(summary)}`;
			}
		}

		await pushGotify(title, truncate(finalMessage, maxChars));
	}

	pi.on("turn_end", async (event, ctx) => {
		try {
			const sessionId = String(ctx?.sessionManager?.getSessionId?.() || "-");
			const message = event?.message;
			if (!message || message.role !== "assistant") return;

			if (message.stopReason === "error") {
				if (!notifyError) return;
				await send(sessionId, "turn_error", "❌ Agent turn failed");
				return;
			}

			if (!notifyComplete) return;
			const assistantText = extractAssistantText(message);
			if (assistantText) {
				await send(
					sessionId,
					"turn_complete",
					`✅ ${escapeMarkdown(preview(assistantText, head, tail))}`,
					assistantText,
				);
			} else {
				await send(sessionId, "turn_complete", "✅ Agent turn completed");
			}
		} catch {
			// Never fail the host runtime due to notifier errors.
		}
	});

	pi.on("tool_call", async (event, ctx) => {
		try {
			if (!notifyQuestion) return;
			if (!event || event.toolName !== "ask") return;

			const sessionId = String(ctx?.sessionManager?.getSessionId?.() || "-");
			const question = extractAskQuestion(event.input);
			const body = question ? `❓ ${escapeMarkdown(preview(question, head, tail))}` : "❓ Waiting for input";
			await send(sessionId, "ask_waiting", body);
		} catch {
			// Never fail the host runtime due to notifier errors.
		}
	});

	pi.on("auto_retry_end", async (event, ctx) => {
		try {
			if (!notifyError) return;
			if (!event || event.success) return;

			const sessionId = String(ctx?.sessionManager?.getSessionId?.() || "-");
			const reason = normalizeText(event.finalError || "");
			const body = reason ? `❌ Retry failed: ${escapeMarkdown(preview(reason, head, tail))}` : "❌ Retry failed";
			await send(sessionId, "auto_retry_end", body);
		} catch {
			// Never fail the host runtime due to notifier errors.
		}
	});
}
