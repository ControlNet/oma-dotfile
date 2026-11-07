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

## Other agents (checked 2026-11-07)

Nothing to change; only Claude Code needed the setting and the hook.

- Codex 0.166:
  - The `git-attribution` extension (`codex-rs/ext/git-attribution`) tells the model to end commits
    with `Co-authored-by: Codex <noreply@openai.com>`, but only when the login uses the Codex backend
    (ChatGPT) and the account's server-side `commit_attribution_enabled` is true. API-key or
    custom-provider auth is always off.
  - There is no `config.toml` key for it. The old `features.codex_git_commit` is listed as `removed`.
  - Each rollout's `world_state` records the result as `git_attribution`. It was `false` in all 70
    sessions with a world state over 30 days, with ChatGPT login and the `codex_api` provider.
  - The commit-msg hook does not strip the Codex trailer. Extend it if that setting ever turns on.
- OMO / oh-my-openagent (omo-ai 5.1.35):
  - `git_master.commit_footer` adds "Ultraworked with [omo](…)" unless it is `false`.
    `git_master.include_co_authored_by` controls the co-author trailer. Both default to `false`.
  - `omo.jsonc` already sets both to `false` under `"[opencode]"` and `"[native]"`.
  - Older versions wrote `Ultraworked with [Sisyphus]` and
    `Co-authored-by: Sisyphus <clio-agent@sisyphuslabs.ai>`. Those show up in upstream ComfyUI
    history from other contributors.
- OpenCode 1.19.5:
  - The only `Co-authored-by` is in `opencode github`, the GitHub Actions agent. It credits the
    GitHub user who triggered the run, not OpenCode.
  - There is no attribution setting.
- OMP 18.14.1:
  - Its `attribution` fields mark who authored a message (`agent`/`user`).
  - `allowAttribution` is a field of the bundled Windsurf team-settings protobuf.
  - Neither touches commits.
- Checked by searching the agent binaries and packages for co-author, attribution and footer
  strings, then reading the upstream source.
- `grep` on that machine is ugrep, so `/usr/bin/grep -a` was used for binaries.
