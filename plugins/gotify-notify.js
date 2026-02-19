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
//   OPENCODE_NOTIFY_SUBAGENT          default false (notify on subagent completion)
//   OPENCODE_NOTIFY_PERMISSION        default true (notify on permission requests)
//   OPENCODE_NOTIFY_ERROR             default true (notify on session errors)
//   OPENCODE_NOTIFY_QUESTION          default true (notify on question tool calls)
//   GOTIFY_NOTIFY_SUMMARIZER_MODEL    e.g. "gpt-5-nano"
//   GOTIFY_NOTIFY_SUMMARIZER_ENDPOINT OpenAI-compatible endpoint, e.g. "https://api.openai.com/v1"
//   GOTIFY_NOTIFY_SUMMARIZER_API_KEY  API key for endpoint auth

const HEAD = Number.parseInt(process.env.OPENCODE_NOTIFY_HEAD || "50", 10);
const TAIL = Number.parseInt(process.env.OPENCODE_NOTIFY_TAIL || "50", 10);

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

  const prompt = `Summarize this in ONE short sentence (max 80 chars). No markdown, no quotes, just plain text:\n\n${input}`;
  const headers = {
    Authorization: `Bearer ${config.apiKey}`,
    "api-key": config.apiKey,
  };

  const chatBody = {
    model: config.model,
    messages: [
      { role: "system", content: "You are a concise summarizer. Output only plain text, no markdown." },
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
        role: "system",
        content: [{ type: "input_text", text: "You are a concise summarizer. Output plain text only." }],
      },
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

       if (event.type === "session.idle") {
         const sessionID = event?.properties?.sessionID;
         if (!sessionID) return;

         try {
           const isChild = await isChildSession(client, sessionID);
           if (isChild) {
            if (NOTIFY_SUBAGENT) {
                await gotifyPush("✅ Subagent task completed");
              }
           } else {
             if (NOTIFY_COMPLETE) {
               await sendLatestAssistant(sessionID);
             }
           }
         } catch (e) {
           console.error("[gotify] session.idle failed:", e?.message || e);
         }
         return;
       }

        if (event.type === "session.error") {
          if (NOTIFY_ERROR) {
            const sessionID = event?.properties?.sessionID;
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

            await gotifyPush("❌ Session encountered an error");
          }
          return;
        }
     },

      "permission.ask": async () => {
        if (NOTIFY_PERMISSION) {
          await gotifyPush("🔐 Permission request");
        }
      },

       "tool.execute.before": async (input, output) => {
         if (input?.tool === "question" && NOTIFY_QUESTION) {
           const firstQuestion = output?.args?.questions?.[0];
           const questionText = firstQuestion?.question || firstQuestion?.header || "Question";
           await gotifyPush("❓ " + escapeMarkdown(preview(questionText, HEAD, TAIL)));
         }
       },
    };
};