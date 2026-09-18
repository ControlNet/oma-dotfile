# Conditional Target Installation Notes

Implemented on 2026-09-18 in `pull.py` as `detect_targets` plus `begin_step` gates in
`main`. Tests live in `tests/test_target_detection.py`.

## Why detection is by executable

Config-directory existence cannot be the signal for the agents. Every `pull.py` run before
this change created `~/.config/opencode`, `~/.omo`, `~/.codex`, `~/.claude` and
`~/.omp/agent` unconditionally, so on any machine that ever ran the installer those
directories exist and prove nothing. The executable is the only honest signal.

## PATH is not enough

Verified install locations on this machine, none of which a bare non-interactive `PATH`
necessarily lists:

- `opencode` -> `~/.opencode/bin`
- `omp` -> `~/.bun/bin`
- `claude` -> `~/.local/bin`
- `codex`, `omo` -> `~/.nvm/versions/node/<version>/bin`

`find_agent_executable` therefore calls `shutil.which(name)` and then
`shutil.which(name, path=extra_bin_search_path())`. Reusing `which`'s `path=` parameter
avoids reimplementing executable-bit and directory checks. `extra_bin_search_path` globs
the nvm directory because the version component is not fixed, and reads `Path.home()` at
call time so tests can patch it.

## Target mapping decisions

- OMO is not detected separately. It is a plugin layer that requires OpenCode, so the
  `opencode` executable gates the OMO config as well. Decided by the user.
- oh-my-pi is detected from `omp` only; `pi` is not probed. Decided by the user.
- The WakaTime step has an outer gate of `codex or claude`, and each plugin still follows
  its own agent inside `ensure_wakatime_plugins`.

## Tokscale exception

Tokscale ships no CLI anywhere on `PATH` but is clearly in use (`~/.config/tokscale` holds
`credentials.json`, `device.json`, `cache/`), so its configuration directory is the signal.
Accepted consequence: once that directory exists — including when a `--all` run created it
— Tokscale always counts as installed afterwards.

## Gotchas found while implementing

- `warn()` writes to stderr while `info()` writes to stdout. When stdout is piped it is
  block-buffered and stderr is not, so a `skipped:` warning printed right after its step
  line appeared *before* it. `warn()` and `error()` now flush stdout first.
- The five unconditional `mkdir` calls at the top of `main` had to move into the gated
  blocks via `prepare_target_dir`, otherwise every directory is still created and the whole
  change is cosmetic. `tests/test_target_detection.py` asserts the directories are absent,
  which is the regression guard for that.
- Step `[8]` (WakaTime) runs before step `[9]` (Claude Code plugin), so it creates
  `claude_config_dir` itself rather than relying on the later step.
- `tests/test_pull_oauth.py` patches `Path.home` but not `shutil.which`, so without an
  explicit `detect_targets` patch it passes only on a machine that happens to have all four
  agents installed.
