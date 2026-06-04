Removed Azure provider support on 2026-06-04.

Support was located in three places:
- `opencode.jsonc`: provider entries `azure-openai` and `azure-anthropic`.
- `pull.py`: installer required-environment warning list included Azure OpenAI variables and Anthropic variables used for Azure Anthropic.
- `README.md`: optional environment variable documentation advertised both Azure providers.

After removal, `opencode.jsonc` only exposes the `codex` provider. The Gotify summarizer's generic OpenAI-compatible endpoint remains unrelated and intentionally kept.
