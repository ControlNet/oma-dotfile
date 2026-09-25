# Shared `_AGENTS.md` audit (2026-09-25)

Follow-up: the user chose to remove the former lines 14 and 15 from the shared
source and the installed Codex, OpenCode, and Claude Code copies. Line numbers
below refer to the version reviewed before that removal.

The same file is installed as global instructions for Codex and OpenCode and
as a user rule for Claude Code. The current installer does not install it to
OMP's native `~/.omp/agent/AGENTS.md`; foreign user context providers in OMP
are opt-in, so an OMP installation should not be inferred from the other copies.

## High-risk instructions

- Line 12 conflicts with line 10: confirming a Python environment does not
  necessarily authorize a project-level AGENTS.md edit. It also mandates a
  repo-root `pyrightconfig.json` even where Pyright is not used or a config
  already exists.
- Line 14 hard-codes `load_skills=["skill-name"]`, which is not a portable
  delegation or skill invocation interface across Codex, Claude Code,
  OpenCode, and OMP. OMP's task subagents have no per-task skill pinning override.
- Line 15 assumes `ui-ux-pro-max` is available everywhere. The installer
  installs `skills/` to Codex and OpenCode, but only the Gotify skill/plugin
  to Claude Code; OMP skills also depend on its discovery configuration.
- Lines 16-17 force `.omo/knowledges` creation or lookup in every Git repo,
  including unrelated or private projects. Make this repo-specific or
  conditional on an existing project convention.
- Line 18 forbids test fixtures and illustrative examples unless highlighted
  to the user, which is too broad for routine tests and documentation.

## Other wording issues

- Line 3 should allow existing non-English identifiers, localization strings,
  and language-specific content where the task requires them.
- Line 5 should say outputs may be public, and secrets belong in private env
  storage; only mention `.env.local` when the project uses it.
- Line 9 should distinguish truly destructive actions from ordinary reviewable
  edits or expected managed-file replacement.
- Line 11 can conflict with a repository's established Python environment
  manager; confirm the project setup first and avoid system-wide installs.
- Line 13 (TDD) should target behavior changes where a test adds confidence.

## Official sources

- Codex instructions: https://learn.chatgpt.com/docs/agent-configuration/agents-md
- Claude Code memory and rules: https://code.claude.com/docs/en/memory
- Claude Code skills: https://code.claude.com/docs/en/skills
- OpenCode rules: https://opencode.ai/docs/rules
- OpenCode skills: https://opencode.ai/docs/skills
- OMP context files: https://github.com/can1357/oh-my-pi/blob/main/docs/context-files.md
- OMP skills: https://github.com/can1357/oh-my-pi/blob/main/docs/skills.md
