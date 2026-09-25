# Claude Code shared instructions from `_AGENTS.md`

Claude Code loads user-level Markdown files under `~/.claude/rules/` on every
session when they have no `paths` frontmatter. Its user-level `CLAUDE.md` also
loads, but placing a repo-managed file there would replace personal instructions.
Copy `_AGENTS.md` to `~/.claude/rules/oma-dotfile.md` instead, using
`$CLAUDE_CONFIG_DIR` when configured.

`pull.py` installs the rule only when Claude Code is detected (or `--all` is
used). It skips identical content and backs up changed content with the existing
`*.bak-<timestamp>` policy unless `NO_BACKUP=1`. It leaves `CLAUDE.md`,
`settings.json`, and unrelated rule files alone. Tests in
`tests/test_target_detection.py` cover content, backup, repeat installation,
and preservation of `CLAUDE.md`.

Claude Code's direct `AGENTS.md` support (v2.1.277+) applies to project
instruction files under the working directory hierarchy and can be suppressed
by a project `CLAUDE.md`. It does not replace the user-level rule mechanism.

Official documentation: https://code.claude.com/docs/en/memory

On 2026-09-25, installed the rule directly to
`/home/zhixi/.claude/rules/oma-dotfile.md` without running the full installer.
The destination did not previously exist, and its bytes matched `_AGENTS.md`
after installation. `claude -p '/context' --output-format text` on Claude Code
2.1.282 listed the path under `Memory Files` with type `User` (843 tokens).
