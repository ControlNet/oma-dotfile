# CI on Linux, macOS and Windows

`.github/workflows/ci.yml` runs on push to master, pull requests, by hand and weekly (upstream
skills, the skills CLI and npm change without a commit here). Each job is a matrix of
ubuntu/macos/windows-latest x Python 3.10/3.14 with `fail-fast: false`.

- `unit`: `python -m unittest discover -s tests`, then `node --test "tests/*.test.mjs"`.
- `install`: `tests/integration/check_install.py` installs on the runner itself (real home,
  real global git config, real npx and upstream skills). It feeds `pull.py` to `python -` on
  stdin with `--repo <checkout> --all`, runs gateway, gateway, `--oauth`, `--oauth`, gateway,
  and checks: exit 0, no traceback or `[ERROR]`, no warning that means a step broke (pattern
  `BROKEN`), expected files exist, `.json`/`.jsonc`/`.toml` parse, a rerun changes no file,
  switching back from `--oauth` restores the gateway files, this repo's skills are in
  `~/.agents/skills` and Claude's skills dir, and a commit through the installed commit-msg
  hook succeeds and loses its `Claude-Session:` line. Windows also runs the README's
  PowerShell one-liner. The script refuses to run without `CI` set.

## Running the install check locally

Never against the real home. A sandbox needs `sh` on PATH too (npx spawns it):

```bash
S=$(mktemp -d); mkdir -p "$S/home" "$S/bin"
for n in git node npx npm sh python3; do ln -s "$(command -v $n)" "$S/bin/$n"; done
env -i HOME="$S/home" PATH="$S/bin" GIT_CONFIG_GLOBAL="$S/gitconfig" GIT_CONFIG_NOSYSTEM=1 CI=1 \
  "$S/bin/python3" tests/integration/check_install.py
```

## What Windows showed

- Redirected stdout/stderr (a pipe or a file, as in CI or `| Tee-Object`) use the ANSI code
  page, cp1252 on English hosts. The banner's box-drawing characters raised
  `UnicodeEncodeError` and ended the run before anything was installed. `Terminal.write` now
  replaces characters the stream cannot encode. An interactive console is UTF-8 and was fine.
- With that fixed, the real install passes on Windows: paths print as `~\.codex`, the
  commit-msg hook (`#!/usr/bin/env python3`) runs under Git for Windows on the runner. A
  machine whose `python3` is only the Microsoft Store alias has not been tested.
- Most unit tests were written for POSIX and fail on Windows for test reasons: POSIX path
  strings compared with `Path` output, raw Windows paths pasted into TOML text, stand-in CLIs
  that rely on shebangs (Windows finds only PATHEXT names such as `.cmd`), `Path.home()`
  reading `USERPROFILE` rather than `HOME`, Unix file modes (0o600), and SQLite state files
  still open when a temporary dir is removed (WinError 32).
