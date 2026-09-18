# Native OpenAI OAuth configuration investigation

## Implemented behavior after user review (2026-09-15)

This section supersedes the original design proposal below. `pull.py --oauth`
is now implemented and covered by `tests/test_pull_oauth.py`. README.md documents
local and streamed invocation on Linux/macOS and PowerShell, authentication,
returning to API mode, and mode-specific Codex/OMP installation behavior.

- Streamed Linux/macOS invocation passes script arguments after Python's stdin
  script marker: `curl -fsSL https://raw.githubusercontent.com/ControlNet/oma-dotfile/master/pull.py | python3 - --oauth`.
  For a local checkout, use `python3 pull.py --oauth`.

- Codex comments only an existing top-level `model_provider = "codex_api"`
  assignment. It adds no provider selector when absent, and preserves other
  provider selections, definitions, and profile settings.
- OpenCode retains the installed custom `codex` provider object if present,
  including legacy JSON configuration. It does not inject the repository's
  provider when absent. Other template settings continue to sync; JSONC comments
  are parsed but the rendered OpenCode output uses formatted JSON.
- OMO converts `codex/` string prefixes to `openai/`; model IDs and reasoning
  levels remain unchanged by user preference.
- OMP converts `codex_api/` selectors to `openai-codex/` and installs an empty
  custom catalog (`providers: {}`). Native model availability must be checked
  after login; there is no account-access guarantee for retained model IDs.
- No extra --api flag was added. At the user's explicit request, running without
  --oauth automatically restores API routing for all three agents. Codex reuses
  its commented gateway selector, avoiding accumulation over repeated switches.
  CODEX_BASE_URL must be set; otherwise the provider edit is skipped as before.
- Credentials are untouched; installed native routing does not enforce OAuth
  when another login method, profile, or explicit model override is selected.
- Full Python stdlib suite: 41 tests passed, including 11 OAuth tests and an
  isolated main-path API -> OAuth -> API installation test. Test data is
  explicitly synthetic. No live installation or authenticated inference ran.


Investigated on 2026-09-15. Installed CLI versions: Codex 0.154.0,
OpenCode 1.18.30, OMP 18.1.3. This is a design investigation; no installer,
template, live configuration, or credential changes were made.

## Current repository routing

- `pull.py::ensure_codex_api_provider_config` selects `codex_api` and writes
  `CODEX_BASE_URL` plus the `CODEX_API_TOKEN` environment variable name.
  An absent URL only skips the edit; it does not reset an existing provider.
- `opencode.jsonc` defines the custom `codex` provider with those environment
  references. `omo.jsonc` explicitly selects `codex/...` in every OpenCode
  agent/category model field. Logging into `openai` does not change those fields.
- `omp_models.yaml` defines `codex_api` using `openai-responses` and an API key.
  The display suffix `(OAuth)` does not imply native OAuth authentication.
- `omp_config.yml` selects `codex_api/...` for all ten model roles.
- `pull.py` currently has no argument parser. Passing `--oauth` now would be
  silently ignored, and the normal installation would still run.
- The installer clones the configured remote revision even when invoked from a
  local checkout. Local template edits alone are not used by installation.

## Native provider routes

### Codex

Select the built-in provider with `model_provider = "openai"`. Keep the custom
`codex_api` definition inactive if convenient for switching back. Use
`codex login` (browser) or `codex login --device-auth` (headless).
`codex login status` checks login status but does not prove inference routing.

`forced_login_method = "chatgpt"` enforces ChatGPT login, but official docs say
incompatible active credentials cause logout and exit. Do not add that setting
silently just to select a provider. A strict OAuth mode should explain this
behavior explicitly. Never set `requires_openai_auth = true` on the existing
third-party provider as a substitute for direct native routing: this changes
authentication while retaining the third-party destination.

Audit explicit provider/endpoint/profile overrides when diagnosing routing.
Preserve user-owned profiles rather than rewriting them wholesale.

### OpenCode and OMO

Use the built-in `openai` provider and its bundled Codex authentication plugin.
The external `opencode-openai-codex-auth` entry is unnecessary for native login.
Use `opencode auth login --provider openai` and select ChatGPT authentication,
or launch OpenCode and use `/connect`, OpenAI, ChatGPT Plus/Pro.

OAuth rendering should omit the managed custom `codex` provider, avoid copying
its `npm`, `baseURL`, `apiKey`, costs, or limits into `openai`, and update every
OMO agent/category model reference. Explicitly set the main model as well so a
remembered custom provider does not decide the next session's default.
Account access and supported model IDs must be checked through `/models`.

### OMP

Use `openai-codex`, not `openai` or `codex_api`. Native transport is
`openai-codex-responses`. In OMP run `/login openai-codex`, then select a model.
All modelRoles need native selectors, including smol, tiny, plan, and task.

Native OAuth needs no custom model catalog. Installing a valid empty custom
catalog (`providers: {}`) for the repository-managed models.yml avoids retaining
an active gateway configuration and prevents fallback to legacy models.yaml or
models.json. Preserve the installer's backup behavior and unrelated files.

The repository disables `codex`, which is a separate discovery namespace; it
does not disable the `openai-codex` provider. Local OMP 18.1.3 source confirms
`openai-codex` has its own OAuth provider and authoritative model discovery.
A models.yml apiKey override outranks stored OAuth: avoid copying gateway key
settings into the native provider.

## Proposed installer interface (not implemented)

- `--oauth`: render native OpenAI routes for Codex, OpenCode/OMO, and OMP;
  skip gateway environment-variable requirements and URL interpolation.
- Consider mutually exclusive `--api` for an explicit return to gateway mode;
  retain the existing API default initially for compatibility and document that
  a later invocation without --oauth reinstalls API mode.
- Authentication stays interactive and owned by each CLI. Never copy tokens
  among applications, invent OAuth credentials, or modify credential stores.
- Preserve the source templates as API defaults; render destination files before
  any installation writes, and reuse the existing backups.
- Separate OAuth model choices from gateway aliases. Do not assume that
  gpt-5.6-sol/luna/terra are accessible just because the gateway accepts them.
  Verify the account model list, or expose explicit OAuth model selections.
  Validate reasoning levels and let native catalogs supply limits and pricing.
- Configuration selection is not an absolute network isolation guarantee:
  explicit CLI overrides, project OMO overrides, resumed sessions, extensions,
  and the independent Gotify summarizer can have their own routing.

## Verification for implementation

Use Python stdlib unittest with explicitly synthetic settings in temporary
directories. Test API -> OAuth -> API, missing gateway environment values,
provider and all role rewrites, preservation of unrelated settings and auth
files, backups, idempotence, argument validation, and the main installation path
with cloning redirected to a local test source. Do not install into the real
home directory as a test. No third-party Python dependencies are needed.

## Sources

- https://developers.openai.com/codex/auth
- https://developers.openai.com/codex/config-reference
- https://opencode.ai/docs/providers/#openai
- https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/plugin/index.ts
- https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/plugin/openai/codex.ts
- https://github.com/can1357/oh-my-pi/blob/main/docs/providers.md
- https://github.com/can1357/oh-my-pi/blob/main/docs/models.md
- Local OMP source: pi-ai/src/registry/openai-codex.ts and
  pi-coding-agent/src/config/model-registry.ts.

## Publication integration and subsequent correction

Upstream 02827d6 initially preserved an existing Codex selector. The user then
explicitly requested automatic return to API mode, superseding that behavior.
Tests cover API selection for both new and existing provider definitions,
missing gateway URLs, OAuth -> API round trips, repeated switching without
accumulating comments, and preservation of nested profile settings. README
now documents fully automatic switching when gateway variables are configured.
Unrelated Claude changes remain excluded from this work.
