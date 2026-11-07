# Claude Code commit attribution (checked 2026-11-07, Claude Code 2.1.319, git 2.34)

- `settings.json` key `attribution` with `{"commit": "", "pr": ""}` hides Claude Code's own commit and
  PR attribution (`Co-Authored-By: Claude`, "Generated with Claude Code"). Its schema text says
  "Empty string hides attribution." The older `includeCoAuthoredBy: false` still exists but is the
  legacy form.
- The setting does not cover lines the model is told to write by its system prompt, such as the
  `Claude-Session: https://claude.ai/code/session_…` trailer some Claude Code sessions request. Those
  were removed by the global `commit-msg` hook (`git-hooks/commit-msg`), and a user rule against
  agent co-author lines takes precedence over that system-prompt request.
- Git has no global hooks dir by default: without `core.hooksPath` it only runs `.git/hooks` of
  each repo. Setting `core.hooksPath` globally makes every repo use that dir and silently ignore its
  own `.git/hooks` (pre-commit framework installs, repo-level git-lfs hooks). husky sets
  `core.hooksPath` per repo, which overrides the global value, so the global hook does not run there.
  `git lfs install` writes its hooks into `core.hooksPath` when it is set.
- `git config --global --type=path --get core.hooksPath` expands `~`. A relative `core.hooksPath` is
  resolved per repo, so a global install cannot target it.
- `pull.py` step 10 (only when Claude Code is detected):
  - merges the attribution setting, with a backup only when it changes;
  - installs `git-hooks/commit-msg` into the global `core.hooksPath` dir, after setting it to
    `~/.config/git/hooks` when unset;
  - backs up a different existing `commit-msg` before replacing it;
  - leaves a relative `core.hooksPath` alone;
  - skips the hook when `python3` is missing, because the `#!/usr/bin/env python3` hook would then
    fail every commit.
- Tests: `tests/test_commit_attribution.py` runs real git against a temporary `GIT_CONFIG_GLOBAL`
  and `HOME`.
