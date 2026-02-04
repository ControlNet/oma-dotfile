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
//   OPENCODE_GOTIFY_NOTIFY_SUMMARIZER format: "provider/model" (e.g., "anthropic/claude-sonnet-4-20250514")

const HEAD = Number.parseInt(process.env.OPENCODE_NOTIFY_HEAD || "50", 10);
const TAIL = Number.parseInt(process.env.OPENCODE_NOTIFY_TAIL || "50", 10);

// Event notification toggles
const NOTIFY_COMPLETE = process.env.OPENCODE_NOTIFY_COMPLETE !== "false";
const NOTIFY_SUBAGENT = process.env.OPENCODE_NOTIFY_SUBAGENT === "true";
const NOTIFY_PERMISSION = process.env.OPENCODE_NOTIFY_PERMISSION !== "false";
const NOTIFY_ERROR = process.env.OPENCODE_NOTIFY_ERROR !== "false";
const NOTIFY_QUESTION = process.env.OPENCODE_NOTIFY_QUESTION !== "false";

// LLM Summarization config
const SUMMARIZER = (process.env.OPENCODE_GOTIFY_NOTIFY_SUMMARIZER || "").trim();
const SUMMARIZER_TIMEOUT = 20000; // 20 seconds
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

function parseSummarizer() {
  if (!SUMMARIZER || !SUMMARIZER.includes("/")) return null;
  const [providerID, ...rest] = SUMMARIZER.split("/");
  const modelID = rest.join("/"); // Handle model IDs with slashes
  return { providerID, modelID };
}

async function summarizeWithLLM(client, text, parentID) {
  const model = parseSummarizer();
  if (!model) return null;
  
  // Truncate long input
  const input = text.length > MAX_INPUT_LENGTH 
    ? text.slice(0, MAX_INPUT_LENGTH) + "..." 
    : text;
  
  let sessionID = null;
  try {
    // Create ephemeral session as child (so it's ignored by isChildSession check)
    const session = await client.session.create({
      body: { title: "[Summarizer]", parentID }
    });
    sessionID = session?.data?.id;
    if (!sessionID) return null;
    
    // Prompt with timeout
    const promptPromise = client.session.prompt({
      path: { id: sessionID },
      body: {
        model,
        tools: {}, // Disable all tools
        parts: [{ 
          type: "text", 
          text: `Summarize this in ONE short sentence (max 80 chars). No markdown, no quotes, just plain text:\n\n${input}`
        }]
      }
    });
    
    const timeoutPromise = new Promise((_, reject) => 
      setTimeout(() => reject(new Error("timeout")), SUMMARIZER_TIMEOUT)
    );
    
    const response = await Promise.race([promptPromise, timeoutPromise]);
    const summary = extractAssistantText(response?.data);
    
    // Validate summary
    if (!summary || summary.length > 200) return null;
    return summary;
    
  } catch {
    return null; // Silent fallback
  } finally {
    // Always cleanup
    if (sessionID) {
      await client.session.delete({ path: { id: sessionID } }).catch(() => {});
    }
  }
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
        if (list[i]?.info?.role === "assistant") {
          last = list[i];
          break;
        }
      }
      if (!last) return;

      const msgID = last?.info?.id;
      if (!msgID) return;

      if (lastSent.get(sessionID) === msgID) return;

      const text = extractAssistantText(last);
      
      // Try LLM summary first, fallback to preview
      let body = await summarizeWithLLM(client, text, sessionID);
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