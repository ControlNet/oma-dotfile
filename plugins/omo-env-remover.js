/**
 * Remove oh-my-opencode dynamic <omo-env> block from system prompts.
 * Helps stabilize prompt prefix for better cache hit rates.
 *
 * @type {import('@opencode-ai/plugin').Plugin}
 */
export async function OmoEnvRemoverPlugin() {
  const OMO_ENV_BLOCK_RE = /<omo-env>[\s\S]*?<\/omo-env>/gi

  return {
    "experimental.chat.system.transform": async (_input, output) => {
      output.system = output.system.map((segment) => {
        if (typeof segment !== "string") return segment

        return segment
          .replace(OMO_ENV_BLOCK_RE, "")
          .replace(/\n{3,}/g, "\n\n")
          .trim()
      })
    },
  }
}
