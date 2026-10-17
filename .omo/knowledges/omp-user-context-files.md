# OMP user-level AGENTS.md discovery (checked 2026-10-17, OMP 18.11.3)

## Finding (before the fix below)

`pull.py` installed no user-level AGENTS.md for OMP. It wrote `_AGENTS.md` to
OpenCode (`~/.config/opencode/AGENTS.md`), Codex (`~/.codex/AGENTS.md`), OMO Native
(`~/.omo/agent/AGENTS.md`) and Claude Code (`~/.claude/rules/oma-dotfile.md`), but
step 6 (OMP) only wrote config.yml, models.yml and the extensions.

## Why OMP ignores ~/.config/opencode/AGENTS.md

- Source: `@oh-my-pi/pi-coding-agent/src/capability/index.ts` `isUserSourceEnabled`.
  `FOREIGN_USER_PROVIDERS` (cursor, codex, claude, claude-plugins, gemini, opencode,
  windsurf, github) only load their `~/` config when listed in `enabledProviders`
  (or `*`/`all`). Native `.omp` and `.agent(s)` are on by default.
- `omp_config.yml` has no `enabledProviders`; its `disabledProviders` also lists
  codex, claude and gemini. So `~/.codex/AGENTS.md` and `~/.gemini/GEMINI.md` are off too.
- Enabling `opencode` would also pull in `~/.config/opencode` skills, commands, MCP
  servers and `plugins/` as extension modules, which is much more than the
  instructions.

## User-level context sources (one wins)

The `context-files` capability keeps one user-level file. The highest-priority
provider shadows the rest (`capability/context-file.ts` key = scope).

| Priority | Provider | User path |
|---|---|---|
| 100 | builtin (native) | `<agentDir>/AGENTS.md` = `~/.omp/agent/AGENTS.md` (`PI_CODING_AGENT_DIR` override) |
| 70 | agents | `~/.agent/AGENTS.md`, `~/.agents/AGENTS.md` |
| 70 | codex (foreign) | `~/.codex/AGENTS.md` |
| 60 | gemini (foreign) | `~/.gemini/GEMINI.md` |
| 55 | opencode (foreign) | `~/.config/opencode/AGENTS.md` |

`contextFiles.extra` adds extra filenames that load alongside the winner instead of
replacing it.

## Implemented (2026-10-17)

Step 6 installs `_AGENTS.md` to `<omp agent dir>/AGENTS.md` with
`install_rendered_text`, the same way step 4 does for OMO Native, so a locally
edited copy is backed up. The native provider has the highest priority and needs
no opt-in. Test: `test_omp_gets_user_level_instructions` in
`tests/test_target_detection.py`.

## Skills (checked 2026-10-17)

- Before the fix: `pull.py` installed repo `skills/` only to OpenCode
  (`~/.config/opencode/skills`, managed items replaced) and Codex
  (`~/.codex/skills`, merged), nothing for OMP.
- `~/.config/opencode/skills` is behind the same foreign opt-in as AGENTS.md, so OMP
  does not see it.
- Native user skills: `<agentDir>/skills/` (builtin provider, `discovery/builtin.ts`).
  `~/.agent(s)/skills` (agents provider) is also on by default.
  `<agentDir>/managed-skills` belongs to autolearn and must not be touched.
- Verified with OMP's own `loadCapability(skillCapability.id)` and an isolated
  `PI_CODING_AGENT_DIR`: all 9 repo skills load from `<agentDir>/skills` as
  `native`/`user` with 0 warnings. With an empty agent dir, none are loaded.
- Implemented 2026-10-17: step 6 copies repo `skills/` to `<agentDir>/skills` with
  `copy_directory_items_replace` (managed skill dirs replaced whole so stale files go;
  the user's other skills and `managed-skills/` are untouched). Test:
  `test_omp_gets_repo_skills_and_keeps_user_skills`.
