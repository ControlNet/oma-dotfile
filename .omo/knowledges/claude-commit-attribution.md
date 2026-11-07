# Claude Code commit attribution (checked 2026-11-07, Claude Code 2.1.319)

- `settings.json` key `attribution` with `{"commit": "", "pr": ""}` hides Claude Code's own commit and
  PR attribution (`Co-Authored-By: Claude`, "Generated with Claude Code"). Its schema text says
  "Empty string hides attribution." The older `includeCoAuthoredBy: false` still exists but is the
  legacy form.
- The setting does not cover lines the model is told to write by its system prompt, such as the
  `Claude-Session: https://claude.ai/code/session_…` trailer some Claude Code sessions request. A user
  rule against agent co-author lines takes precedence over that request, but the model can still slip.
- `pull.py` step 10 (only when Claude Code is detected) merges the attribution setting, with a backup
  only when it changes, and installs the `strip-attribution` plugin from `claude-plugins/`.

## strip-attribution plugin

- A PreToolUse hook on `Bash`. It rewrites `git commit` and `gh pr create|edit` commands, dropping
  whole lines (and `-m`/`--trailer` arguments) that are `Co-Authored-By: Claude …@anthropic.com`,
  `🤖 Generated with [Claude Code](…)` or `Claude-Session: https://claude.ai/code/session_…` (the bare
  link too: Claude Code asks for it that way at the end of PR descriptions). A closing `"`, `'` or `)`
  on such a line, and the command after it, is kept. Files named by `-F`/`--file`/`--body-file` are
  cleaned in place before the command runs.
- Limitation: once a commit command is anywhere in the Bash call, every attribution-only line in the
  call is dropped, including one in another command's heredoc (`cat > notes.md <<EOF … && git commit`).
- It must not block: a `deny`/exit-2 hook makes Claude retry the command, which costs a turn. Output
  `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "updatedInput": {...}}}` with no
  `permissionDecision`. Checked with `claude -p --model haiku --settings <file>`:
  - The command runs rewritten; Claude sees no difference and does not retry (2 turns end to end).
  - Permission rules still apply, to the rewritten command: an unallowed `touch` was refused and the
    refusal showed the rewritten text. `updatedInput` must hold the whole `tool_input` (keep
    `description`).
- Testing it: `claude -p --plugin-dir claude-plugins/strip-attribution` loads it without installing.
  Haiku refuses to run a commit with attribution when the user's own rules forbid it, unless the
  prompt says the command tests the hook that removes those lines. An allow rule such as
  `Bash(git commit:*)` does not match `git -c … commit`.

## Global git hooks (tried, abandoned on 2026-11-07)

Versions `eaccad9` to `b182b57` used a global `commit-msg` hook instead. It worked, but needed too
much machinery, and the next `pull.py` puts back what they replaced (`remove_git_hook_chain`).

- Git has no global hooks dir by default. Setting `core.hooksPath` globally makes every repo use that
  dir and silently ignore its own `.git/hooks` (pre-commit framework installs, repo-level git-lfs
  hooks). husky sets `core.hooksPath` per repo, which overrides the global value.
- Keeping repo hooks running meant a chain script under every hook name in githooks(5), drop-in
  `<name>.d/` dirs, and regenerating git-lfs's hooks. A review found further gaps: include/system
  config, `proc-receive` stdin/stdout, hooks that find files relative to `$0`, `GIT_DIR` leaking into
  nested git calls, and symlinked hooks.
- Git 2.54 (released 2026-04-20) adds config-defined hooks (`hook.<name>.command`, `hook.<name>.event`)
  that run alongside the hookdir hook, which would avoid the chain. Ubuntu 26.04 ships git 2.53 and
  24.04 ships 2.43, so it is not available without the git-core PPA.
- Facts found on the way:
  - `git rev-parse --git-path hooks/<name>` resolves to `core.hooksPath` itself; the repo's own hooks
    dir is `$(git rev-parse --git-common-dir)/hooks`.
  - With a foreign `pre-push` already in `core.hooksPath`, `git lfs install` prints
    "Hook already exists" and skips its hooks. `git -c core.hooksPath=<tmp> lfs install --local` in a
    scratch repo writes them into `<tmp>`.
  - `git lfs post-commit` creates `.git/lfs` in every repo, so that dir does not show a repo uses LFS.
  - `push-to-checkout` changes git's behavior just by existing: with
    `receive.denyCurrentBranch=updateInstead`, git updates the pushed-to worktree only without it.
- What `remove_git_hook_chain` undoes, in the global `core.hooksPath` dir: files marked
  `# managed by oma-dotfile` get back `<name>.d/previous*`, else the newest `<name>.bak-*`, else
  `<name>.d/git-lfs`, else (commit-msg) `drop-claude-attribution`; unmarked hooks are never touched.
  Our drop-ins are deleted, other `<name>.d/` files are kept with a warning, and `core.hooksPath` is
  left set, since nothing shows who set it. The `eaccad9` state (only a Python `commit-msg`, no marker)
  cannot be told apart from a user's own hook, so it is left for manual cleanup.

## Other agents (checked 2026-11-07)

Nothing to change; only Claude Code needed the setting and the plugin.

- Codex 0.166:
  - The `git-attribution` extension (`codex-rs/ext/git-attribution`) tells the model to end commits
    with `Co-authored-by: Codex <noreply@openai.com>`, but only when the login uses the Codex backend
    (ChatGPT) and the account's server-side `commit_attribution_enabled` is true. API-key or
    custom-provider auth is always off.
  - There is no `config.toml` key for it. The old `features.codex_git_commit` is listed as `removed`.
  - Each rollout's `world_state` records the result as `git_attribution`. It was `false` in all 70
    sessions with a world state over 30 days, with ChatGPT login and the `codex_api` provider.
  - The strip-attribution plugin only runs in Claude Code, so it would not strip the Codex trailer.
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
