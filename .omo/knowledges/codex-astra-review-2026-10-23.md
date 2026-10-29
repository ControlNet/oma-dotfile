# Codex gpt-6-astra review of the repo (2026-10-23)

Commit ids below are the ones after the 2026-10-29 history rewrite (see [[knowledge-notes-privacy]]).

Ran `codex exec -m gpt-6-astra -c model_reasoning_effort=high -s read-only --ephemeral`
(codex-cli 0.162.1). It made no file changes. It reported 9 findings,
all of which Claude checked against the code. Fix status is below.

| # | Sev | Where | Problem | Repro status |
|---|---|---|---|---|
| 1 | high | `pull.py` `find_first_toml_section_idx`, `replace_toml_section`, `find_toml_key_assignment_ranges` | A table header with a trailing comment (`[profiles.work] # x`) is not seen as a section. Updating `[model_providers.codex_api]` then swallows the following table, or a commented provider header gets a second copy appended (`TOMLDecodeError: Cannot declare ... twice`). `notify = [...]` text inside a multi-line string such as `developer_instructions` is rewritten, so the real top-level `notify` is never added. | Reproduced (all three cases) |
| 2 | high | `pull.py` `cleanup_old_backups` | Backups are made with `shutil.copy2` (keeps the source mtime) but pruned by mtime. A config restored with an old mtime makes the backup just taken the "oldest", and it is deleted (default `MAX_BACKUPS=1`) before the file is overwritten. | Reproduced |
| 3 | high | `pull.py` `ensure_codex_notify_config_lines` | The Windows `notify = ["C:\...", ...]` is written unescaped, so the TOML fails to parse (`Unescaped '\'`). README documents a PowerShell install. | Reproduced |
| 4 | medium | `codex-gotify-notify.py` `_post_json` http_error log; `plugins/gotify-notify.js` `logSummarizerError` -> `reportDiagnostic` (toast) | HTTP error bodies are logged (and toasted in OpenCode) without redaction. Only a problem if a server echoes secrets. | Confirmed by reading |
| 5 | medium | `pull.py` `ensure_wakatime_config` | An existing 0644 cfg keeps 0644 when `api_key` is written. This was a deliberate choice; reconsider and tighten to 0600 when writing a key. | Confirmed (by design) |
| 6 | medium | `codex-gotify-notify.py` `_sessions_root_path`, `_goals_db_path`, `_tui_log_path` | These hardcode `~/.codex` and ignore `CODEX_HOME`. The dedup cache and the execution log do too. | Confirmed by reading |
| 7 | medium | `pull.py` `ensure_codex_wakatime_plugin` / `ensure_claude_wakatime_plugin` | These use `shutil.which` on PATH only, while detection also searches `EXTRA_BIN_DIRS`, and they run bare `codex`/`claude`. A non-interactive shell missing `~/.bun/bin` etc. detects the agent but skips the plugin. | Confirmed by reading |
| 8 | medium | `plugins/gotify-notify.js` `gotifyPush` | `fetch` has no timeout/AbortSignal, and permission/question hooks await it. | Confirmed by reading |
| 9 | medium | `plugins/gotify-notify.js` `sendLatestAssistant` | `lastSent` is set even when the push failed, so the same message is never retried. | Confirmed by reading |

## Fix status (2026-10-23)

| # | Commit | Notes |
|---|---|---|
| 3 | 1b7fede | `toml_basic_string` (JSON escaping, `ensure_ascii=False`); POSIX output unchanged |
| 2 | 9e45e5f | prune by the stamp in the backup name |
| 1 | 5077b72 | statement scan (`toml_statement_starts`); headers may carry comments or quoted parts; when tomllib rejects a value, fall back to bracket/quote balance. A real-world `config.toml` renders unchanged in OAuth mode |
| 5 | 4deb521 | chmod 0600 before writing `api_key` into an existing cfg |
| 7 | 97c3373 | plugin CLIs via `find_agent_executable`, absolute path, dir prepended to PATH; nvm dirs now newest first (an older node can hold a codex without the `plugin` command) |
| 8, 9 | 2d2b623 | `OPENCODE_NOTIFY_GOTIFY_TIMEOUT_SEC` (1..5, default 5); `gotifyPush` returns success and `lastSent` is set only on success; first tests: `tests/opencode-gotify-notify.test.mjs` |
| 6 | 31447e7 (2026-10-29) | `_codex_home()`: non-empty `CODEX_HOME`, else `~/.codex` (same as Codex and `pull.py` `get_codex_dir`); sessions, goals DB, TUI log, dedup cache and execution log use it; explicit `CODEX_NOTIFY_*` paths still win |
| 4 | open | lower priority; not fixed |

## Round 2 (HEAD 2d2b623)

Same command (`codex exec -m gpt-6-astra -c model_reasoning_effort=high -s read-only --ephemeral`).
All 8 findings verified locally; none of the round-1 fixes regressed.

| # | Sev | Where | Finding | Local check |
|---|-----|-------|---------|-------------|
| R2-1 | high | `skills/secret-guard/scripts/scan_secrets.py` `get_files`/`scan_content` | `staged` mode takes names from the index but reads the working tree, so a secret staged then removed from the working copy is missed; deleted-but-staged files are skipped by `isfile()` | code read: `open(filepath)` on the working copy |
| R2-2 | medium | `pull.py` fallback scanner (`tomllib=None`, Python 3.10) | `"""Say "done""""` (valid TOML: 4-5 closing quotes) is misread, later tables get swallowed, `notify` lands in `profiles.work` | reproduced: tomllib path top-level, fallback path `profiles.work.notify` |
| R2-3 | medium | `pull.py` `ensure_wakatime_config` | early `already matches` return skips the chmod, so a 0644 cfg written by an older installer stays 0644 | reproduced: mode stays `0o644` |
| R2-4 | medium | `pull.py` `ensure_codex_oauth_provider_config` | quoted key `"model_provider" = "codex_api"` and multi-line value `"""\ncodex_api"""` survive `--oauth` | reproduced: both stay `codex_api` |
| R2-5 | medium | `skills/ui-ux-pro-max/scripts/design_system.py` `persist_design_system` | `--page X --persist` always rewrites `MASTER.md` with the page query's design | code read: unconditional `open(master_file, "w")` |
| R2-6 | medium | `plugins/gotify-notify.js` `scheduleIdleCheck` | pending state is deleted before summarize/push, so a `busy` during a slow summary cannot cancel; old turn's completion is pushed | code read: `cancelled` not re-checked after `summarizeWithLLM` |
| R2-7 | medium | `omp-gotify-notify.js` `shouldSend` | dedup cache is written before send and the push result is ignored; a retry within the 15 s window after a 503 is dropped | code read: `sentCache.set` before `pushGotify` |
| R2-8 | low | `omp-wakatime-sync.js` `resolveCli` | only checks `isFile()`; a non-executable candidate shadows a working CLI later in the list, EACCES does not fall through | code read |

### Round 2 fix status (all fixed, TDD, one commit each; pushed 2026-10-23)

| # | Commit | Notes |
|---|--------|-------|
| R2-3 | 86f1d55 | chmod moved before the `already matches` return |
| R2-7 | 5a9f460 | key still reserved before push (drops concurrent duplicates), released on failure |
| R2-1 | a7d0b41 | staged mode reads `git show :<path>`; names via `-z`; works from subdirs too |
| R2-4 | 3a8484d | whole assignment by normalized key; multiline collapsed to `# model_provider = "codex_api"` so API mode can restore; fallback (no tomllib) reads single-line values only |
| R2-6 | 8885efd | pending state kept until the send ends; `state.cancelled` rechecked before push |
| R2-8 | 7ffcdf2 | auto candidates need `X_OK`; explicit `OMP_WAKATIME_CLI` unchanged; spawn-time EACCES fallthrough not added |
| R2-2 | 14a874e | `toml_value_is_complete` consumes up to 2 extra quotes before a closing triple quote |
| R2-5 | 1110846 | `--page` run writes MASTER.md only if missing; SKILL.md documents it |
| flake | 3d6bb29 | `omp-wakatime-sync` test cleanup: `rmSync(..., {maxRetries: 10, retryDelay: 50})`; cause was detached fake clis still writing into tmp |

Gotchas learned:
- zsh: `echo ====` fails (`=cmd` expansion); quote it.
- Test values for secret scanners: `password = "test-only-fake-password"` matches "Password Assignment" without tripping GitHub push protection.
