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

Product bugs CI found, all fixed:

- Redirected stdout/stderr (a pipe or a file, as in CI, `| Tee-Object` or an agent running a
  script) use the ANSI code page, cp1252 on English hosts. The installer's banner and the
  secret scanner's `▸ ✓ ✗` raised `UnicodeEncodeError`; the scanner then exited 1, which
  reads as a finding. Both now print `?` for what the stream cannot encode.
- `subprocess.run(text=True)` decodes with that code page too: the secret scanner garbled
  UTF-8 file names from Git, so `git show` missed them and they went unscanned. Decode Git
  output as UTF-8.
- `Path.write_text` translates `\n` to `\r\n` on Windows. `Files.write_text` compares the
  LF bytes first, so every run rewrote and backed up files such as OMP's `models.yml`. Write
  with `newline="\n"`. The install check now fails when a rerun lists any change, since a
  rewrite with the same bytes is invisible to a file snapshot.
- `with sqlite3.connect(...) as db:` only commits; the connection stays open (a
  ResourceWarning on 3.13+, a locked file on Windows). Wrap it in `contextlib.closing`.

Writing tests that pass on Windows (`tests/support.py`):

- Stand-in CLIs: `write_cli(path, script)` and `link_cli(path, target)`. Windows ignores
  shebangs and `which` finds only PATHEXT names, so they become `<name>.cmd`; `which` reports
  them as `<name>.CMD`. Node refuses to spawn `.cmd` without a shell, so Node tests that need
  a stand-in to run check the logged spawn on Windows instead.
- A cleared env needs `SYSTEMROOT` (Python 3.10 cannot start without it), `COMSPEC`,
  `PATHEXT`, `TEMP`/`TMP`, and `USERPROFILE`: `Path.home()` and Node's `os.homedir()` read
  it, not `HOME`.
- Build expected paths with `Path(...)`/`os.sep`, quote paths put into TOML with
  `toml_basic_string`, write fixtures that are compared as bytes with `newline="\n"`, and use
  `TestCase.assertMode`, which checks permission bits on POSIX only.
- An untested gap: a machine whose `python3` is only the Microsoft Store alias.
