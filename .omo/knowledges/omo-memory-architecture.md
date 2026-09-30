# OMO memory system architecture (omo-ai 5.1.0)

Source: `~/.bun/install/global/node_modules/omo-ai/plugin/extensions/` (`omo.js` minified,
`reflection-persona.md`, `dream-persona.md`, `facts-persona.md`, `kibitzer-persona.md`).

## Storage

- Root: `~/.omo/memory/agents/<repo-name>-<hash>/` (override with `OMO_MEMORY_HOME`).
- `repo/` is a git repo holding the memory itself:
  - `system/*.md`: always projected into the primary agent prompt (`persona`, `human`,
    `boundaries` = user's exact words, `self-aware` = max 12 confirmed self-observations).
  - `skills/<name>/SKILL.md`: procedural memory; only descriptions are in context.
  - everything else (`reference/`, `notes/facts/YYYY-MM.md`, `people/`, `ARCHIVE.md`):
    external memory, fetched on demand by name/description.
- `runtime/`: transcripts, facts-queue, reflection runs/completions/park state, worktrees,
  locks, recall sidecars. Not memory content.

## Scope: project-level (per absolute path)

- Identity = `<slug(basename)>-<sha256(absolute project root path)[:8]>`, e.g.
  `printf '%s' /home/zhixi/GitRepos/oma-dotfile | sha256sum | cut -c1-8` -> `fcb2ff61`.
- Moving/cloning the project to a different absolute path yields a new, empty memory.
- `memory.agent` (default `"auto"`) overrides this; a non-auto value is hashed as-is, so
  `<value>-<sha256(value)[:8]>` is path-independent. Config can live in `~/.omo/omo.jsonc`
  or project `<repo>/.omo/omo.jsonc`.
- `system/human.md` is per identity, so user facts are not shared between projects.

## Cross-machine sync (one-way mirror only)

- `/memory-repository set <url>` stores `omo.memoryRepository.url` in the memory repo's local
  git config and pushes `main` immediately; also `status`, `push`, `unset`.
- omo installs a `post-commit` hook in `repo/.git/hooks/` that pushes `main:main` (no force)
  after every commit; log in `repo/.git/memory-repository-push.log`.
- There is no fetch/pull/clone logic: a second machine does not import the mirror, and two
  machines committing independently diverge (push rejected as non-fast-forward).
- Practical setup: private mirror repo; keep the same absolute path (or the same explicit
  `memory.agent`) on every machine; with omo stopped, `git clone` the mirror into
  `~/.omo/memory/agents/<id>/repo` on the new machine, then `/memory-repository set <url>`
  there too (local git config is not cloned); `git -C <repo> pull --ff-only` before each
  session. Clone-in-place bootstrap not verified end-to-end as of 2026-09-29.

## Background agents

- **Reflection**: after `memory.reflection.trigger.step_count` (default 25) steps or on
  compaction, a sandboxed child (category `quick`, bwrap on Linux, 15 min timeout) reads a
  transcript window, edits memory in a git worktree, commits, and merges into `repo/`.
  Manual: `/reflect`.
- **Dream**: cross-session consolidation after idle (`idle_minutes` default 30): dedupe,
  promote/demote files between `system/` and `reference/` using usage ledgers, keep
  `system/` under `compile_warn_tokens` (default 30000), archive facts older than 6 months,
  audit skills, derive people observations. Manual: `/dream`.
- **Facts extractor**: turns queued transcript entries into atomic dated facts
  (`record_fact`, person or project scope).
- **Kibitzer**: read-only per-session advisor; watches events and `nudge`s the primary agent
  with already-stored memories relevant to the next step (default max 2 per wake).

## Commands

`/reflect`, `/dream`, `/search`, `/people`.

## Related

- [[omo-memory-reflection-bwrap-missing-dir]] for the parked-reflection bwrap failure.
