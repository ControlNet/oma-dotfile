# Antigravity CLI (agy) and shared skills

Checked against agy 1.5.4 and skills CLI 1.7.6 (2026-11-10), with canary skills and
`agy -p` in an empty directory.

## Where agy looks for skills

- Global discovery: `~/.gemini/config/skills/<name>/SKILL.md`. Workspace: `.agents/skills/`
  (also `.agent/`, `_agents/`, `_agent/`), walking up to the repository root.
- Declared paths: `~/.gemini/config/skills.json` (global) or `.agents/skills.json` (workspace):
  `{"entries": [{"path": "~/some/dir", "exclude": ["regex"]}], "inherits": [...]}`. Each entry
  directory is scanned one level deep; `~/` and absolute paths work globally. Workspace
  manifests only load from inside the workspace (no absolute, `../` or symlinked paths).
- Precedence, highest first: workspace, workspace-declared, `~/.gemini/config/`, built-in,
  global-declared. So skills added through the global `skills.json` lose name clashes.
- The built-in `agy-customizations` skill under `~/.gemini/antigravity-cli/builtin/skills/`
  is the most complete local reference (`docs/skills.md`, `docs/json_configs.md`).

## What does not work

- agy does not read `~/.agents/skills` by default (asked for installed shared skills: none).
- The skills CLI `--agent antigravity` target installs to `~/.gemini/antigravity/skills`,
  which is the Antigravity IDE's directory; agy did not see a skill placed there.

## What works

- A canary in `~/.gemini/config/skills/` and one in a directory named by
  `~/.gemini/config/skills.json` were both listed, and `agy -p "/<skill-name>"` loaded and
  followed the skill body.
- So one global entry `{"path": "~/.agents/skills"}` exposes every shared skill without
  copies or links, and `npx skills update -g` keeps updating them in place.

## Limits to remember

- `SKILL.md` needs `name` and `description` frontmatter; `name` should match the directory.
- Skill bodies over 24 KB are flagged (`agy plugin validate` warns); `skill-creator` from
  anthropics/skills is about 33 KB.
- `agy -p` with `--mode plan` answers a skill invocation by writing a plan; use the default
  mode to see the skill run.
