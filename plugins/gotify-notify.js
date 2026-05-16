import os from "node:os";
import path from "node:path";

// ~/.config/opencode/plugins/gotify-notify.js
//
// Env (Required):
//   GOTIFY_URL
//   GOTIFY_TOKEN_FOR_OPENCODE
//
// Optional:
//   OPENCODE_NOTIFY_TITLE             override default "OpenCode :: <project>@<hostname>"
//   OPENCODE_NOTIFY_HEAD              default 50
//   OPENCODE_NOTIFY_TAIL              default 50
//   OPENCODE_NOTIFY_COMPLETE          default true (notify on root session completion)
//   OPENCODE_NOTIFY_IDLE_CONFIRM_MS   default 10000 (check session status before notify)
//   OPENCODE_NOTIFY_SUBAGENT          default false (notify on subagent completion)
//   OPENCODE_NOTIFY_PERMISSION        default true (notify on permission requests)
//   OPENCODE_NOTIFY_ERROR             default true (notify on session errors)
//   OPENCODE_NOTIFY_QUESTION          default true (notify on question tool calls)
//   OPENCODE_NOTIFY_MAX_CHARS         default 280
//   OPENCODE_NOTIFY_USER_AGENT        optional; default mimics browser UA
//   GOTIFY_NOTIFY_SUMMARIZER_MODEL    e.g. "gpt-5-nano"
//   GOTIFY_NOTIFY_SUMMARIZER_ENDPOINT OpenAI-compatible endpoint, e.g. "https://api.openai.com/v1"
//   GOTIFY_NOTIFY_SUMMARIZER_API_KEY  API key for endpoint auth
//   GOTIFY_NOTIFY_SUMMARIZER_RESPONSES default false for Google AI Studio, true otherwise

const HEAD = Number.parseInt(process.env.OPENCODE_NOTIFY_HEAD || "50", 10);
const TAIL = Number.parseInt(process.env.OPENCODE_NOTIFY_TAIL || "50", 10);
const MAX_CHARS_RAW = Number.parseInt(process.env.OPENCODE_NOTIFY_MAX_CHARS || "280", 10);
const MAX_CHARS = Number.isFinite(MAX_CHARS_RAW) && MAX_CHARS_RAW > 0
  ? MAX_CHARS_RAW
  : 280;
const IDLE_CONFIRM_MS_RAW = Number.parseInt(process.env.OPENCODE_NOTIFY_IDLE_CONFIRM_MS || "10000", 10);
const IDLE_CONFIRM_MS = Number.isFinite(IDLE_CONFIRM_MS_RAW)
  ? Math.max(0, IDLE_CONFIRM_MS_RAW)
  : 10000;

// Event notification toggles
const NOTIFY_COMPLETE = process.env.OPENCODE_NOTIFY_COMPLETE !== "false";
const NOTIFY_SUBAGENT = process.env.OPENCODE_NOTIFY_SUBAGENT === "true";
const NOTIFY_PERMISSION = process.env.OPENCODE_NOTIFY_PERMISSION !== "false";
const NOTIFY_ERROR = process.env.OPENCODE_NOTIFY_ERROR !== "false";
const NOTIFY_QUESTION = process.env.OPENCODE_NOTIFY_QUESTION !== "false";

// LLM Summarization config
const SUMMARIZER_MODEL = (process.env.GOTIFY_NOTIFY_SUMMARIZER_MODEL || "").trim();
const SUMMARIZER_ENDPOINT = normalizeBase(process.env.GOTIFY_NOTIFY_SUMMARIZER_ENDPOINT || "");
const SUMMARIZER_API_KEY = (process.env.GOTIFY_NOTIFY_SUMMARIZER_API_KEY || "").trim();
const SUMMARIZER_TIMEOUT = 120000; // 120 seconds
const MAX_INPUT_LENGTH = 5000; // Truncate before sending to LLM

function notifyUserAgent() {
  const custom = (process.env.OPENCODE_NOTIFY_USER_AGENT || "").trim();
  if (custom) return custom;
  return "Mozilla/5.0 (X11; Linux x86_64) OpenCodeGotifyNotify/1.0";
}

function hostname() {
  return normalizeText(os.hostname() || process.env.HOSTNAME || "unknown-host");
}

function projectNameFromPath(cwd) {
  const text = toNonEmptyString(cwd);
  if (!text) return "unknown-project";
  const normalized = path.normalize(text);
  const base = path.basename(normalized);
  return normalizeText(base || "unknown-project");
}

function isProjectPathCandidate(cwd) {
  const text = toNonEmptyString(cwd);
  if (!text) return false;
  return projectNameFromPath(text) !== "unknown-project";
}

function getOpenCodeCwd({ directory, worktree, project } = {}) {
  const candidates = [
    typeof directory === "string" ? directory : directory?.path,
    typeof project === "string" ? project : project?.directory,
    typeof worktree === "string" ? worktree : worktree?.path,
    typeof project === "string" ? project : project?.path || project?.root || project?.worktree,
    process.cwd(),
  ];

  for (const candidate of candidates) {
    const cwd = toNonEmptyString(candidate);
    if (isProjectPathCandidate(cwd)) return cwd;
  }
  return "";
}

function buildNotifyTitle(agentName, cwd) {
  const override = toNonEmptyString(process.env.OPENCODE_NOTIFY_TITLE);
  if (override) return override;
  return `${agentName} :: ${projectNameFromPath(cwd)}@${hostname()}`;
}

function normalizeBase(url) {
  const u = (url || "").trim();
  return u.endsWith("/") ? u.slice(0, -1) : u;
}

function normalizeText(s) {
  return String(s || "").replace(/\s+/g, " ").trim();
}

function stripThoughtBlocks(s) {
  const raw = String(s || "");
  if (!raw.trim()) return "";

  const withoutBlocks = raw.replace(/<thought>[\s\S]*?<\/thought>/gi, " ");
  const cleaned = normalizeText(withoutBlocks);
  if (cleaned) return cleaned;

  const withoutTags = raw.replace(/<\/?thought>/gi, " ");
  return normalizeText(withoutTags);
}

function preview(s, head = 50, tail = 50) {
  const t = normalizeText(s);
  if (!t) return "";
  if (t.length <= head + tail + 3) return t;
  return `${t.slice(0, head)}…${t.slice(-tail)}`;
}

function formatErrorNotification(error) {
  const errorName = normalizeText(error?.name || "");
  const errorMessage = normalizeText(
    typeof error?.message === "string"
      ? error.message
      : typeof error === "string"
        ? error
        : ""
  );

  if (errorName && errorMessage) {
    return `❌ ${escapeMarkdown(errorName)}: ${escapeMarkdown(errorMessage)}`;
  }

  if (errorMessage) {
    return `❌ ${escapeMarkdown(errorMessage)}`;
  }

  if (errorName) {
    return `❌ ${escapeMarkdown(errorName)}`;
  }

  return "❌ Session encountered an error";
}

function extractAssistantText(msg) {
  const parts = msg?.parts || [];
  return normalizeText(
    parts
      .filter((p) => p?.type === "text" && typeof p.text === "string")
      .map((p) => p.text)
      .join("")
  );
}

function escapeMarkdown(s) {
  const text = String(s ?? "");
  const escapeSet = new Set([
    "\\", "`", "*", "_", "~",
    "[", "]", "(", ")",
    "#", "+", "-", ".", "!",
    ">", "|", "{", "}"
  ]);

  let out = "";
  for (const ch of text) {
    if (escapeSet.has(ch)) out += "\\" + ch;
    else out += ch;
  }
  return out;
}

function toNonEmptyString(value) {
  if (typeof value !== "string") return "";
  const text = value.trim();
  return text.length > 0 ? text : "";
}

function getSessionIDFromEvent(event) {
  const props = event?.properties;
  const info = props?.info;
  const candidates = [
    props?.sessionID,
    props?.sessionId,
    props?.id,
    props?.threadID,
    props?.threadId,
    props?.conversationID,
    props?.conversationId,
    info?.sessionID,
    info?.sessionId,
    info?.id,
  ];
  for (const candidate of candidates) {
    const sessionID = toNonEmptyString(candidate);
    if (sessionID) return sessionID;
  }
  return "";
}

function getStatusTypeFromEvent(event) {
  const statusType = toNonEmptyString(event?.properties?.status?.type);
  if (statusType) return statusType;
  if (event?.type === "session.idle") return "idle";
  if (event?.type === "session.busy") return "busy";
  return "";
}

function isIdleStatusEvent(event) {
  return event?.type === "session.status" && getStatusTypeFromEvent(event) === "idle";
}

function isIdleEvent(event) {
  return event?.type === "session.idle" || isIdleStatusEvent(event);
}

function isNonIdleStatusEvent(event) {
  if (event?.type !== "session.status" && event?.type !== "session.busy") return false;
  const statusType = getStatusTypeFromEvent(event);
  return !!statusType && statusType !== "idle";
}

async function shouldNotifyCompletion(client, sessionID) {
  try {
    const response = await client.session.status();
    const statusMap = response?.data;
    if (!statusMap || typeof statusMap !== "object") return true;

    const status = statusMap[sessionID];
    if (!status || typeof status !== "object") {
      return true;
    }

    return status.type === "idle";
  } catch (error) {
    console.error("[gotify] session.status check failed:", error?.message || error);
    return true;
  }
}

function summarizerConfig() {
  if (!SUMMARIZER_MODEL || !SUMMARIZER_ENDPOINT || !SUMMARIZER_API_KEY) return null;
  return {
    model: SUMMARIZER_MODEL,
    endpoint: SUMMARIZER_ENDPOINT,
    apiKey: SUMMARIZER_API_KEY,
  };
}

function endpointJoin(base, path) {
  if (!base) return "";
  if (base.endsWith(path)) return base;
  return `${base}${path}`;
}

function isGoogleAIStudioEndpoint(endpoint) {
  try {
    const host = new URL(endpoint).hostname.toLowerCase();
    return host === "generativelanguage.googleapis.com" || host.endsWith(".generativelanguage.googleapis.com");
  } catch {
    return endpoint.toLowerCase().includes("generativelanguage.googleapis.com");
  }
}

function shouldTryResponsesEndpoint(endpoint) {
  const override = (process.env.GOTIFY_NOTIFY_SUMMARIZER_RESPONSES || "").trim().toLowerCase();
  if (["1", "true", "yes", "on"].includes(override)) return true;
  if (["0", "false", "no", "off"].includes(override)) return false;
  return !isGoogleAIStudioEndpoint(endpoint);
}

function summarizerHeaders(endpoint, apiKey) {
  if (isGoogleAIStudioEndpoint(endpoint)) {
    return { Authorization: `Bearer ${apiKey}` };
  }

  return {
    Authorization: `Bearer ${apiKey}`,
    "api-key": apiKey,
  };
}

function extractOpenAIText(payload) {
  if (!payload || typeof payload !== "object") return "";

  const outputText = payload.output_text;
  if (typeof outputText === "string" && outputText.trim()) {
    return stripThoughtBlocks(outputText);
  }

  const output = payload.output;
  if (Array.isArray(output)) {
    for (const item of output) {
      if (!item || typeof item !== "object") continue;
      const content = item.content;
      if (!Array.isArray(content)) continue;
      for (const part of content) {
        if (!part || typeof part !== "object") continue;
        if (typeof part.text === "string" && part.text.trim()) {
          return stripThoughtBlocks(part.text);
        }
      }
    }
  }

  const choices = payload.choices;
  if (Array.isArray(choices)) {
    for (const choice of choices) {
      if (!choice || typeof choice !== "object") continue;
      const message = choice.message;
      if (!message || typeof message !== "object") continue;
      if (typeof message.content === "string" && message.content.trim()) {
        return stripThoughtBlocks(message.content);
      }
    }
  }

  return "";
}

function logSummarizerError(stage, message, detail = "") {
  const suffix = detail ? ` ${preview(detail, 120, 120)}` : "";
  console.error(`[gotify] summarizer ${stage} ${message}${suffix}`);
}

async function postJSON(url, body, headers, timeoutMs, stage) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "User-Agent": notifyUserAgent(),
        ...headers,
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    const rawText = await response.text().catch(() => "");
    if (!response.ok) {
      logSummarizerError(stage, `HTTP ${response.status} ${response.statusText}`, rawText);
      return null;
    }

    if (!rawText) {
      logSummarizerError(stage, "returned empty response body");
      return null;
    }

    const data = JSON.parse(rawText);
    if (!data || typeof data !== "object") {
      logSummarizerError(stage, "returned non-object JSON", rawText);
      return null;
    }
    return data;
  } catch (e) {
    if (e?.name === "AbortError") {
      logSummarizerError(stage, `timed out after ${timeoutMs}ms`);
    } else {
      logSummarizerError(stage, e?.message || "request failed");
    }
    return null;
  } finally {
    clearTimeout(timeout);
  }
}

async function summarizeWithLLM(text) {
  const config = summarizerConfig();
  if (!config || !text || !text.trim()) return null;

  const input = text.length > MAX_INPUT_LENGTH
    ? text.slice(0, MAX_INPUT_LENGTH) + "..."
    : text;

  const prompt = `You are a concise summarizer. Output plain text only.\nUse the same language as the input text.\nSummarize this in ONE short sentence (max 80 chars). No markdown, no quotes, just plain text:\n\n${input}`;
  const headers = summarizerHeaders(config.endpoint, config.apiKey);

  const chatBody = {
    model: config.model,
    messages: [
      { role: "user", content: prompt },
    ],
    max_tokens: 80,
  };
  const chatData = await postJSON(
    endpointJoin(config.endpoint, "/chat/completions"),
    chatBody,
    headers,
    SUMMARIZER_TIMEOUT,
    "chat/completions",
  );
  if (chatData) {
    const summary = extractOpenAIText(chatData);
    if (summary && summary.length <= 200) return summary;
    if (!summary) {
      logSummarizerError("chat/completions", "returned no extractable summary");
    } else {
      logSummarizerError(
        "chat/completions",
        `returned summary longer than 200 chars (${summary.length})`,
        summary,
      );
    }
  }

  if (!shouldTryResponsesEndpoint(config.endpoint)) {
    logSummarizerError("responses", "skipped because endpoint does not advertise OpenAI Responses compatibility");
    return null;
  }

  const responsesBody = {
    model: config.model,
    input: [
      {
        role: "user",
        content: [{ type: "input_text", text: prompt }],
      },
    ],
    max_output_tokens: 80,
    reasoning: { effort: "low" },
  };
  const responsesData = await postJSON(
    endpointJoin(config.endpoint, "/responses"),
    responsesBody,
    headers,
    SUMMARIZER_TIMEOUT,
    "responses",
  );
  if (!responsesData) return null;
  const summary = extractOpenAIText(responsesData);
  if (!summary) {
    logSummarizerError("responses", "returned no extractable summary");
    return null;
  }
  if (summary.length > 200) {
    logSummarizerError(
      "responses",
      `returned summary longer than 200 chars (${summary.length})`,
      summary,
    );
    return null;
  }
  return summary;
}

async function gotifyPush(title, message) {
   const base = normalizeBase(process.env.GOTIFY_URL);
   const token = (process.env.GOTIFY_TOKEN_FOR_OPENCODE || "").trim();
   if (!base || !token || !message) return;

   const res = await fetch(`${base}/message`, {
     method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Gotify-Key": token,
        "User-Agent": notifyUserAgent(),
      },
      body: JSON.stringify({ title, message: truncateText(message, MAX_CHARS), priority: 5 }),
    });

   if (!res.ok) {
     const text = await res.text().catch(() => "");
     console.error(`[gotify] HTTP ${res.status} ${res.statusText} ${text}`);
   }
}

function truncateText(text, limit) {
  const value = String(text || "");
  if (limit <= 0 || value.length <= limit) return value;
  if (limit <= 3) return value.slice(0, limit);
  return value.slice(0, limit - 3) + "...";
}

async function isChildSession(client, sessionID) {
   try {
     const response = await client.session.get({ path: { id: sessionID } });
     return !!response?.data?.parentID;
   } catch {
     return false;
   }
}

export const GotifyNotify = async ({ client, directory, worktree, project }) => {
    const defaultCwd = getOpenCodeCwd({ directory, worktree, project });
   const lastSent = new Map();
    const pendingIdleTimers = new Map();
    const sessionParentCache = new Map();
    const sessionRootCache = new Map();
    const sessionDirectoryCache = new Map();

    function clearPendingIdle(sessionID) {
      const pending = pendingIdleTimers.get(sessionID);
      if (pending) {
        pending.cancelled = true;
        clearTimeout(pending.timer);
        pendingIdleTimers.delete(sessionID);
      }
    }

    async function getParentSessionID(sessionID) {
      if (sessionParentCache.has(sessionID)) {
        return sessionParentCache.get(sessionID);
      }

      try {
        const response = await client.session.get({ path: { id: sessionID } });
        const parentID = toNonEmptyString(response?.data?.parentID);
        sessionParentCache.set(sessionID, parentID);
        return parentID;
      } catch {
        return "";
      }
    }

    async function getSessionDirectory(sessionID) {
      if (!sessionID) return "";
      if (sessionDirectoryCache.has(sessionID)) {
        return sessionDirectoryCache.get(sessionID);
      }

      try {
        const response = await client.session.get({ path: { id: sessionID } });
        const session = response?.data;
        const cwd = getOpenCodeCwd({
          directory: session?.directory,
          worktree: session?.worktree,
          project: session?.project,
        });
        sessionDirectoryCache.set(sessionID, cwd);
        return cwd;
      } catch {
        sessionDirectoryCache.set(sessionID, "");
        return "";
      }
    }

    async function notifyTitleForSession(sessionID) {
      const sessionDirectory = await getSessionDirectory(sessionID);
      return buildNotifyTitle("OpenCode", sessionDirectory || defaultCwd);
    }

    async function getRootSessionID(sessionID) {
      if (!sessionID) return "";
      if (sessionRootCache.has(sessionID)) {
        return sessionRootCache.get(sessionID);
      }

      const chain = [];
      const visited = new Set();
      let currentID = sessionID;

      while (currentID && !visited.has(currentID)) {
        if (sessionRootCache.has(currentID)) {
          const cachedRootID = sessionRootCache.get(currentID);
          for (const id of chain) sessionRootCache.set(id, cachedRootID);
          return cachedRootID;
        }

        visited.add(currentID);
        chain.push(currentID);

        const parentID = await getParentSessionID(currentID);
        if (!parentID) {
          for (const id of chain) sessionRootCache.set(id, currentID);
          return currentID;
        }

        currentID = parentID;
      }

      for (const id of chain) sessionRootCache.set(id, sessionID);
      return sessionID;
    }

    async function hasRunningSubagentForRoot(rootSessionID) {
      try {
        const response = await client.session.status();
        const statusMap = response?.data;
        if (!statusMap || typeof statusMap !== "object") return false;

        for (const [sessionID, status] of Object.entries(statusMap)) {
          if (!sessionID || sessionID === rootSessionID) continue;
          if (!status || typeof status !== "object" || status.type === "idle") continue;

          const resolvedRootID = await getRootSessionID(sessionID);
          if (resolvedRootID === rootSessionID) {
            return true;
          }
        }

        return false;
      } catch (error) {
        console.error("[gotify] subagent status check failed:", error?.message || error);
        return false;
      }
    }

    function scheduleIdleCheck(sessionID, state, delayMs) {
      state.timer = setTimeout(async () => {
        if (state.cancelled) return;

        try {
          const hasRunningSubagent = await hasRunningSubagentForRoot(sessionID);
          if (state.cancelled) return;

          if (hasRunningSubagent) {
            scheduleIdleCheck(sessionID, state, IDLE_CONFIRM_MS);
            return;
          }

          pendingIdleTimers.delete(sessionID);

          const stillIdle = await shouldNotifyCompletion(client, sessionID);
          if (!stillIdle || state.cancelled) return;
          await sendLatestAssistant(sessionID);
        } catch (err) {
          pendingIdleTimers.delete(sessionID);
          console.error("[gotify] delayed idle notify failed:", err?.message || err);
        }
      }, Math.max(0, delayMs));
    }

     async function sendLatestAssistant(sessionID) {
       const resp = await client.session.messages({ path: { id: sessionID } });
      const list = resp?.data || [];
      if (!Array.isArray(list) || list.length === 0) return;

      let last = null;
      for (let i = list.length - 1; i >= 0; i--) {
        const msg = list[i];
        if (msg?.info?.role === "assistant" && !msg?.info?.summary) {
          last = msg;
          break;
        }
      }
      if (!last) return;

      const msgID = last?.info?.id;
      if (!msgID) return;

      if (lastSent.get(sessionID) === msgID) return;

      const text = extractAssistantText(last);
      
      // Try LLM summary first, fallback to preview
      let body = await summarizeWithLLM(text);
      if (!body) {
        body = preview(text, HEAD, TAIL);
      }
      
      if (!body) return;
      await gotifyPush(await notifyTitleForSession(sessionID), "✅ " + escapeMarkdown(body));
      lastSent.set(sessionID, msgID);
    }

    return {
      event: async ({ event }) => {
        if (!event?.type) return;

        if (isNonIdleStatusEvent(event)) {
          const sessionID = getSessionIDFromEvent(event);
          if (sessionID) {
            clearPendingIdle(sessionID);
          }
          return;
        }

        if (isIdleEvent(event)) {
          const sessionID = getSessionIDFromEvent(event);
         if (!sessionID) return;

         try {
           const isChild = await isChildSession(client, sessionID);
           if (isChild) {
            if (NOTIFY_SUBAGENT) {
                await gotifyPush(await notifyTitleForSession(sessionID), "✅ Subagent task completed");
              }
            } else {
              if (NOTIFY_COMPLETE) {
                clearPendingIdle(sessionID);

                const pending = {
                  cancelled: false,
                  timer: null,
                };
                pendingIdleTimers.set(sessionID, pending);
                scheduleIdleCheck(sessionID, pending, IDLE_CONFIRM_MS);
              }
            }
          } catch (e) {
            console.error("[gotify] idle completion check failed:", e?.message || e);
          }
          return;
        }

        if (event.type === "session.error") {
          if (NOTIFY_ERROR) {
            const sessionID = getSessionIDFromEvent(event);
            const error = event?.properties?.error;

            // Skip abort errors (normal cancellation, e.g. background_cancel)
            const errorName = error?.name || "";
            const errorMsg = String(error?.message || error || "");
            if (errorName === "AbortedError" || errorMsg.includes("aborted")) {
              return;
            }

            // Skip child session errors (subagent/summarizer)
            if (sessionID) {
              try {
                const isChild = await isChildSession(client, sessionID);
                if (isChild) return;
              } catch {}
            }

            await gotifyPush(await notifyTitleForSession(sessionID), formatErrorNotification(error));
          }
          return;
        }
     },

      "permission.ask": async (permission) => {
        if (NOTIFY_PERMISSION) {
          await gotifyPush(await notifyTitleForSession(permission?.sessionID), "🔐 Permission request");
        }
      },

       "tool.execute.before": async (input, output) => {
         if (input?.tool === "question" && NOTIFY_QUESTION) {
           const firstQuestion = output?.args?.questions?.[0];
           const questionText = firstQuestion?.question || firstQuestion?.header || "Question";
           await gotifyPush(await notifyTitleForSession(input?.sessionID), "❓ " + escapeMarkdown(preview(questionText, HEAD, TAIL)));
         }
       },
    };
};
