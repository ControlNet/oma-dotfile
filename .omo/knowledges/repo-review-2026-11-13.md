# Repo review (2026-11-13)

Read-only deep review of the installer package, `pull.py`, the commit-msg hook, the Gotify
notifiers (Codex, Claude Code, OpenCode, OMP), the OMP WakaTime sync, the env-remover plugin and
the secret-guard scanner. Python suite: 367 tests pass; `node --test tests/*.test.mjs`: 36 pass.
Nothing was fixed in this pass. Reproductions ran in throwaway dirs and repos with
`GIT_CONFIG_GLOBAL` pointed at a scratch file.

## Findings, most severe first

C = confirmed by a reproduction, P = plausible from reading.

1. **commit-msg hook aborts commits (C).** `path.read_text()` decodes strictly. With
   `git commit -v` (or `commit.verbose=true`) the message file holds the staged diff, so any
   staged latin-1/GBK text makes it raise; the commit fails in every repo, because the hook sits in
   the global `core.hooksPath`. Same with `i18n.commitEncoding` set to a non-UTF-8 encoding. On
   Windows the locale encoding is used (P). It also rewrites the file when nothing matched, and
   `splitlines()` turns `\f`, U+2028 and U+0085 into line breaks, CRLF into LF, and drops trailing
   blank lines under `--cleanup=verbatim` (C). Fix: work on bytes, split on `b"\n"` only, write
   only on change, catch everything and exit 0.
2. **Legacy skill cleanup follows a symlinked dir (C, not live here).** If
   `<agent>/skills` is a symlink to `~/.agents/skills`, `remove_legacy_skill_copies` deletes the
   freshly installed shared skills; next run reinstalls, then deletes again. Fix: skip a skill dir
   whose `resolve()` is the shared dir.
3. **`Files.prune` deletes the backup it just made (C).** It globs `<name>.bak-*` and sorts by
   name, so a hand-made `opencode.jsonc.bak-mine` sorts after the stamps and survives while the new
   `.bak-<stamp>` is removed (keep=1). Fix: only count names matching `bak-\d{8}-\d{6}`.
4. **Codex `config.toml` can be left invalid (C).** A `codex_api` provider written inline
   (`[model_providers]` + `codex_api = {...}`, dotted keys, or `model_providers = {...}`) gets a
   second `[model_providers.codex_api]` appended; Codex then cannot parse its config.
   `keep_valid_toml` guards only the skills edit. Fix: validate the whole transform result.
5. **Expected failures abort the run instead of warning (C).** Against the documented rule:
   `--oauth` with a malformed existing `opencode.jsonc` (ValueError out of `install_oauth_file`);
   a CLI printing non-UTF-8 (`Runner.run` uses `text=True`, UnicodeDecodeError is not a
   `CommandFailed`; Windows locale decoding is P); a latin-1 `config.toml` (`warns_on(OSError)`
   only); `MAX_BACKUPS=abc`; `pull.py` with no git on PATH (FileNotFoundError traceback).
6. **BOM in `config.toml` (C).** `﻿[features]` is not seen as a header, so `notify` and
   `model_provider` are appended under the first real table (`features.notify`); Codex gets no
   notifier and no provider.
7. **LINES codec splits on U+2028 (C).** A basic string containing it is rewritten across two
   lines: invalid TOML. Same root cause as item 1.
8. **yaml_merge drops user keys (C).** A comment or blank line inside a flat block makes
   `flat_mapping` return None, so the managed block replaces the user's whole block, losing keys
   only the user had (the docstring promises they are kept). A leading comment or `---` makes the
   merge fail and the file is replaced (backup kept).
9. **Literal backslashes in Codex and OpenCode notifications (C for the text; rendering assumes
   Gotify's plain-text default).** `_escape_markdown`/`escapeMarkdown` run, but no
   `extras["client::display"].contentType = "text/markdown"` is sent, e.g.
   `Done\. Fixed the parser \(see README\.md\)`. Claude Code and OMP do not escape. No test pins it.
10. **secret-guard false negatives (C).** The generic assignment regexes are case-sensitive and
    need quotes: `OPENAI_API_KEY = "..."`, `export NOTION_API_TOKEN=ntn_...`, YAML/INI unquoted
    keys (`api_key: ...`, `api_key = waka_...`) and `hf_` tokens are all missed. Only lowercase
    quoted `api_key = "..."` is caught. `SK[a-f0-9]{32}` (Twilio) has no word boundary.
11. **Codex notifier silenced by the user's own prompt (C).** `_approval_reviewer_prompt_seen`
    filters by role only for dict messages; Codex's `input-messages` are plain strings (user
    prompts), so a prompt mentioning "approval reviewer" and "approval request" drops that turn's
    notification. Fix: only consider dict messages with a developer/system role.

Lower: `same_tree` ignores `dircmp.common_funny` (file vs dir with the same name reads as equal,
so a broken plugin dir is never replaced, C); an offline run wipes the skill commit record (7 → 0)
so the next run reinstalls everything (C); WakaTime warns "codex not found" on Claude-only machines
(`ensure_plugins` tries both CLIs regardless of `ctx.found`, C); the Codex notifier and OpenCode
plugin logs never rotate (Claude and OMP rotate at 256 KiB); the Codex notifier summarizes before
dedup, and keys dedup on the summarized text, so a duplicate event costs a second LLM call and may
be sent twice (P); `_thread_source_flags` runs three times per event, each a recursive glob of
`~/.codex/sessions` plus up to 3×2 MiB of rollouts and 8 MiB of TUI log; `_json_post` does not catch
UnicodeDecodeError; OpenCode session-id Maps are never pruned; hooks pin the installer's
`sys.executable`, so a transient interpreter (pixi exec, a deleted venv) silently breaks the Claude
hooks and the Codex notify; after a gateway install, `--oauth` keeps the gateway `codex` provider in
`opencode.jsonc` (cannot tell its own from a user's); OMP `models.yml` lacks `gpt-6-astra`
(known, see opencode-gpt-6-astra.md).

## Deliberate, documented

Global `core.hooksPath` disabling per-repo hooks (README); installer-owned `notify`, profile
entries included (codex-notify-installer-overwrite.md); managed OMP keys and lists win
(yaml_merge docstring); one backup per file by default (README).

## Checked and found consistent

Model ids referenced by `opencode.jsonc`, `omo.jsonc` and OMP `config.yml` exist in their catalogs,
also after the `--oauth` renderings; the Claude hooks rewrite keeps `args`; the OMP goal state
machine matches the README; the OMP WakaTime sync and env-remover plugin; the TOML editors on
multiline notify arrays; `HomeAsTilde` path masking.
