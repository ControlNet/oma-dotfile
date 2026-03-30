// ~/.config/opencode/plugins/gotify-notify.js
//
// Env (Required):
//   GOTIFY_URL
//   GOTIFY_TOKEN_FOR_OPENCODE
//
// Optional:
//   OPENCODE_NOTIFY_HEAD              default 50
//   OPENCODE_NOTIFY_TAIL              default 50
//   OPENCODE_NOTIFY_COMPLETE          default true (notify on root session completion)
//   OPENCODE_NOTIFY_IDLE_CONFIRM_MS   default 10000 (check session status before notify)
//   OPENCODE_NOTIFY_SUBAGENT          default false (notify on subagent completion)
//   OPENCODE_NOTIFY_PERMISSION        default true (notify on permission requests)
//   OPENCODE_NOTIFY_ERROR             default true (notify on session errors)
//   OPENCODE_NOTIFY_QUESTION          default true (notify on question tool calls)
//   GOTIFY_NOTIFY_SUMMARIZER_MODEL    e.g. "gpt-5-nano"
//   GOTIFY_NOTIFY_SUMMARIZER_ENDPOINT OpenAI-compatible endpoint, e.g. "https://api.openai.com/v1"
//   GOTIFY_NOTIFY_SUMMARIZER_API_KEY  API key for endpoint auth

const HEAD = Number.parseInt(process.env.OPENCODE_NOTIFY_HEAD || "50", 10);
const TAIL = Number.parseInt(process.env.OPENCODE_NOTIFY_TAIL || "50", 10);
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

function normalizeBase(url) {
  const u = (url || "").trim();
  return u.endsWith("/") ? u.slice(0, -1) : u;
}

function normalizeText(s) {
  return String(s || "").replace(/\s+/g, " ").trim();
}

function preview(s, head = 50, tail = 50) {
  const t = normalizeText(s);
  if (!t) return "";
  if (t.length <= head + tail + 3) return t;
  return `${t.slice(0, head)}…${t.slice(-tail)}`;
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

function extractOpenAIText(payload) {
  if (!payload || typeof payload !== "object") return "";

  const outputText = payload.output_text;
  if (typeof outputText === "string" && outputText.trim()) {
    return normalizeText(outputText);
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
          return normalizeText(part.text);
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
        return normalizeText(message.content);
      }
    }
  }

  return "";
}

async function postJSON(url, body, headers, timeoutMs) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...headers,
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!response.ok) return null;
    const data = await response.json().catch(() => null);
    if (!data || typeof data !== "object") return null;
    return data;
  } catch (e) {
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
  const headers = {
    Authorization: `Bearer ${config.apiKey}`,
    "api-key": config.apiKey,
  };

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
  );
  if (chatData) {
    const summary = extractOpenAIText(chatData);
    if (summary && summary.length <= 200) return summary;
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
  );
  if (!responsesData) return null;
  const summary = extractOpenAIText(responsesData);
  if (!summary || summary.length > 200) return null;
  return summary;
}

async function gotifyPush(message) {
   const base = normalizeBase(process.env.GOTIFY_URL);
   const token = (process.env.GOTIFY_TOKEN_FOR_OPENCODE || "").trim();
   if (!base || !token || !message) return;

   const res = await fetch(`${base}/message`, {
     method: "POST",
     headers: {
       "Content-Type": "application/json",
       "X-Gotify-Key": token,
     },
     body: JSON.stringify({ title: "OpenCode", message, priority: 5 }),
   });

   if (!res.ok) {
     const text = await res.text().catch(() => "");
     console.error(`[gotify] HTTP ${res.status} ${res.statusText} ${text}`);
   }
}

async function isChildSession(client, sessionID) {
   try {
     const response = await client.session.get({ path: { id: sessionID } });
     return !!response?.data?.parentID;
   } catch {
     return false;
   }
}

export const GotifyNotify = async ({ client }) => {
   const lastSent = new Map();
    const pendingIdleTimers = new Map();
    const sessionParentCache = new Map();
    const sessionRootCache = new Map();

    function clearPendingIdle(sessionID) {
      const pending = pendingIdleTimers.get(sessionID);
      if (pending) {
        pending.cancelled = true;
        clearTimeout(pending.timer);
        pendingIdleTimers.delete(sessionID);
      }
    }

    async function shouldIgnoreSession(sessionID) {
      if (!sessionID) return false;
      return isChildSession(client, sessionID);
    }

    function getErrorName(error) {
      return toNonEmptyString(error?.name);
    }

    function getErrorMessage(error) {
      const candidates = [
        error?.message,
        error?.data?.message,
        error?.error?.message,
      ];
      for (const candidate of candidates) {
        const text = toNonEmptyString(candidate);
        if (text) return text;
      }
      return toNonEmptyString(String(error || ""));
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
      await gotifyPush("✅ " + escapeMarkdown(body));
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
           if (await shouldIgnoreSession(sessionID)) return;
           if (NOTIFY_COMPLETE) {
             clearPendingIdle(sessionID);

             const pending = {
               cancelled: false,
               timer: null,
             };
             pendingIdleTimers.set(sessionID, pending);
             scheduleIdleCheck(sessionID, pending, IDLE_CONFIRM_MS);
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
            const errorName = getErrorName(error);
            const errorMsg = getErrorMessage(error).toLowerCase();
            if (
              errorName === "AbortedError" ||
              errorName === "AbortError" ||
              errorName === "MessageAbortedError" ||
              errorMsg.includes("aborted")
            ) {
              return;
            }

            if (await shouldIgnoreSession(sessionID)) return;

            await gotifyPush("❌ Session encountered an error");
          }
          return;
        }
     },

      "permission.ask": async (input) => {
        if (NOTIFY_PERMISSION) {
          if (await shouldIgnoreSession(input?.sessionID)) return;
          await gotifyPush("🔐 Permission request");
        }
      },

       "tool.execute.before": async (input, output) => {
         if (input?.tool === "question" && NOTIFY_QUESTION) {
           if (await shouldIgnoreSession(input?.sessionID)) return;
           const firstQuestion = output?.args?.questions?.[0];
           const questionText = firstQuestion?.question || firstQuestion?.header || "Question";
           await gotifyPush("❓ " + escapeMarkdown(preview(questionText, HEAD, TAIL)));
         }
       },
    };
};
