# OpenCode managed item install behavior

`pull.py` installs OpenCode `plugins/` and `skills/` with per-item replacement rather than replacing the whole parent directory. The helper `copy_directory_items_replace()` removes and recopies each same-named source item so repo-managed plugin/skill directories do not retain stale files, while unrelated user-created items under the destination parent are preserved.

Codex skills intentionally still use `copy_directory_merge()`, which merge-copies contents and preserves unrelated existing files.
