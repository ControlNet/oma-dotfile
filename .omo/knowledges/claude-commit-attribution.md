# Claude Code commit attribution (checked 2026-11-07, Claude Code 2.1.319, git 2.34)

- `settings.json` key `attribution` with `{"commit": "", "pr": ""}` hides Claude Code's own commit and
  PR attribution (`Co-Authored-By: Claude`, "Generated with Claude Code"). Its schema text says
  "Empty string hides attribution." The older `includeCoAuthoredBy: false` still exists but is the
  legacy form.
- The setting does not cover lines the model is told to write by its system prompt, such as the
  `Claude-Session: https://claude.ai/code/session_…` trailer some Claude Code sessions request. Those
  were removed by the global `commit-msg` hook (now `git-hooks/drop-claude-attribution`), and a user rule against
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
  - sets `core.hooksPath` to `~/.config/git/hooks` when unset, and leaves a relative value alone;
  - installs nothing when `python3` is missing;
  - installs `git-hooks/chain` under every name in `GIT_CHAINED_HOOKS`.
- Global hooks layout (drop-in dirs, since 2026-11-07). Hook-specific knowledge lives in `<name>.d/`,
  not in the chain script:
  - `chain` runs every executable in `<name>.d/`, sorted, then the repo's own hook, stopping at the
    first failure.
  - With one runner it `exec`s it, which keeps `proc-receive`'s stdin/stdout protocol intact. With
    several, stdin is saved to a temp file and fed to each (skipped when stdin is a terminal).
  - `commit-msg.d/drop-claude-attribution` is the original Python hook, unchanged.
  - `<name>.d/git-lfs` is written by git-lfs itself: `git -c core.hooksPath=<tmp> lfs install --local`
    inside a scratch repo writes its hooks there and leaves the global config alone. Run outside a
    repo, `git lfs install` writes no hooks. `--manual` printed nothing there.
  - When git-lfs is missing, the `git-lfs` drop-ins are removed. When it fails, they are kept.
  - A foreign hook already in the dir moves to `<name>.d/previous`, or `previous-N`, and keeps
    running. It is dropped when the same bytes are already in `<name>.d/`, which covers Git LFS's own
    hooks and the first commit-msg version.
  - Symlinks and non-files are left alone, with a warning.
  - Files marked `# managed by oma-dotfile` are replaced.
  - `GIT_RETIRED_HOOK_FILES` removes the managed top-level `push-to-checkout` and
    `drop-claude-attribution` left by earlier versions.
- Upgrading from earlier versions was checked on 2026-11-07. Each version was installed from git
  history into a sandbox whose hooks dir already held Git LFS's own hooks, then the new version was
  installed on top.
  - Versions checked: `eaccad9` (Python `commit-msg` only), `2ada252` (LFS-aware chain plus
    `push-to-checkout`) and `21567f0`.
  - All three ended the same: 25 chains and 5 drop-ins, no other files, a silent second run, Claude
    lines dropped and LFS objects pushed.
  - The `<name>.bak-<stamp>` files those versions left are removed when their content is in
    `<name>.d/`. Others are listed every run as not running.
  - If git-lfs was upgraded between versions, its old hook text differs from what it writes now. It
    then lands in `<name>.d/previous` next to `git-lfs` and LFS runs twice; that is harmless but
    slower.
- Hook names:
  - Git runs only the names in githooks(5). A repo hook under any other name never ran anyway.
  - `GIT_CHAINED_HOOKS` is githooks(5) of git 2.34 (28 names) minus `GIT_UNCHAINED_HOOKS`.
  - The test compares it with `man githooks`, so a git that adds a hook fails the test instead of
    silently skipping that repo hook.
  - There is no command that lists hooks: git 2.34 has no `git hook`, and
    `/usr/share/git-core/templates/hooks` has only 13 samples.
- Chaining facts:
  - `git rev-parse --git-path hooks/<name>` resolves to `core.hooksPath` itself, so a chain using it
    would call itself forever. Use `$(git rev-parse --git-common-dir)/hooks/<name>`; this also works
    from linked worktrees and bare repos.
  - With a foreign `pre-push` already in `core.hooksPath`, `git lfs install` prints
    "Hook already exists" and skips its hooks, though it still writes the `filter.lfs.*` config.
  - `git lfs post-commit` creates `.git/lfs` in every repo, so that dir does not show a repo uses LFS.
  - `git lfs pre-push` needs a named remote to find its endpoint. Pushing to a bare path fails with
    "missing protocol".
  - `push-to-checkout` is not chained, because its existence changes git's behavior: with
    `receive.denyCurrentBranch=updateInstead`, git updates the pushed-to worktree only when no such
    hook exists. A chain exiting 0 left the worktree stale while the push succeeded.
  - `post-index-change` is not chained (it runs on every index write), and neither is
    `fsmonitor-watchman` (called through the `core.fsmonitor` path).
  - `reference-transaction` is chained and costs one `sh` plus `git rev-parse` per ref transaction.
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
