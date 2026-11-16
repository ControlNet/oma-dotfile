# CI on Linux, macOS and Windows

`.github/workflows/ci.yml` runs on push to master, pull requests, by hand and weekly (upstream
skills, the skills CLI, npm and the agent CLIs change without a commit here). Every job runs
on ubuntu/macos/windows-latest with `fail-fast: false`.

| Job | Python | What it covers |
|---|---|---|
| `unit` | 3.10, 3.14 | `python -m unittest discover -s tests`, then `node --test "tests/*.test.mjs"` |
| `install` | 3.10, 3.14 | `check_install.py --clone`: no agent CLIs, `--all`; pull.py clones the branch as the one-liners do. Windows also runs the README's PowerShell one-liner with `--repo .` |
| `install-home` | 3.14 | `check_install.py` with HOME (and USERPROFILE) in `home dir/Zoë Example`, run by a venv inside it, so the hooks' interpreter path has both too |
| `install-agents` | 3.10, 3.14 | every agent CLI installed, `check_install.py --agents` |

## What `tests/integration/check_install.py` checks

It installs on the runner itself (real home, real global git config, real npx and upstream
skills), feeding `pull.py` to `python -` on stdin: gateway, gateway, `--oauth`, `--oauth`,
gateway. It refuses to run without `CI` set.

- Exit 0, no traceback or `[ERROR]`, no warning that means a step broke (`BROKEN`).
- Expected files exist; `.json`/`.jsonc`/`.toml` parse.
- A rerun changes no file (snapshot) and reports no change: no `- ` item line except
  "unchanged" summaries, and no `[SUCCESS]` but "Installation complete!". A rewrite with the
  same bytes is invisible to a snapshot.
- Switching back from `--oauth` restores the gateway files.
- This repo's skills are in `~/.agents/skills` and Claude's skills dir.
- A commit through the installed commit-msg hook loses its `Claude-Session:` line, once with
  the normal PATH and once with only git on PATH (no Python).
- The Antigravity CLI's Stop hook, run as agy runs it (`sh -c`, or `cmd /c` on Windows, in the
  plugin dir, `PLUGIN_DATA` set): it prints only `{}`, and its detached worker posts the
  transcript's last response (CJK and a check mark, so the code pages are crossed) to the Gotify
  stand-in. In every job, since agy itself never runs a hook without a login.

With `--agents`:

- No `--all`: the agents must be detected, and **any warning outside `ALLOWED_WARNINGS`
  fails**. A skipped step is a gap in the check, not a pass. The `--all` legs without CLIs
  showed only "claude not found; skip ..." annotations, which is how the CLI-driven steps
  (WakaTime plugins, herdr-dag, agy's skills.json) went untested.
- Each CLI loads what was installed. Each command was checked against a deliberately broken
  config first: `codex features list`, `opencode debug config`, `omp config list` exit
  non-zero; `omo --list-models` exits 0 but prints `Warning: ... JSON Parse error`; `claude
  plugin list --json` exits 0 with every plugin `enabled: false` when settings.json is broken,
  so the check asserts the WakaTime and gotify-notify plugins are enabled. `agy plugin list
  --json` drops `hooks` when hooks.json does not parse, so it must show the oma-dotfile plugin
  enabled with its rules and hook; `agy plugin validate` must report notes only.
- The installed Claude Code Stop hook and the Codex `notify` command run against a local HTTP
  stand-in for Gotify; each must post one message with the expected text, and run its
  interpreter by absolute path.
- CLI checks and hooks run last: they write their own state into the dirs the snapshots cover.

CLI sources: npm `@anthropic-ai/claude-code @openai/codex opencode-ai omo-ai` (omo-ai needs
Node 24+), `bun install -g @oh-my-pi/pi-coding-agent` (needs Bun 1.4.4+), Herdr from its GitHub
release assets, agy from `https://antigravity.google/cli/install.sh` / `install.ps1`. Claude
Code and Codex plugin commands work without logging in. Tokscale is detected by its config
dir only, so CI creates an empty one (a stand-in for a machine it ran on).

## Running the install check locally

Never against the real home. A sandbox needs `sh` on PATH too (npx spawns it):

```bash
S=$(mktemp -d); mkdir -p "$S/home" "$S/bin"
for n in git node npx npm sh python3; do ln -s "$(command -v $n)" "$S/bin/$n"; done
env -i HOME="$S/home" PATH="$S/bin" GIT_CONFIG_GLOBAL="$S/gitconfig" GIT_CONFIG_NOSYSTEM=1 CI=1 \
  "$S/bin/python3" tests/integration/check_install.py
```

For `--agents`, install the CLIs into a prefix (`npm install -g --prefix "$S/prefix" ...`,
`BUN_INSTALL="$S/bun" bun install -g ...`), put those bins first on PATH and
`mkdir -p "$S/home/.config/tokscale"`. For `--clone`, set `REPO_REV` to a pushed branch.

## What CI found

- Redirected stdout/stderr on Windows use the ANSI code page (cp1252 on English hosts). The
  installer's banner and the secret scanner's `▸ ✓ ✗` raised `UnicodeEncodeError`; the scanner
  then exited 1, which reads as a finding. Both now print `?` for what the stream cannot
  encode. The install check itself needed the same (`reconfigure(errors="replace")`).
- `subprocess.run(text=True)` decodes with that code page too: the secret scanner garbled
  UTF-8 file names from Git, so they went unscanned. Decode Git output as UTF-8.
- `Path.write_text` translates `\n` to `\r\n` on Windows, so every run rewrote and backed up
  files such as OMP's `models.yml`. Write with `newline="\n"`.
- `with sqlite3.connect(...) as db:` only commits; wrap it in `contextlib.closing`.
- With Codex installed, the second install rewrote `config.toml`: replacing the gateway
  provider table dropped the blank line before the tables Codex appends. `--all` without
  Codex never got there.
- The commit-msg hook was `#!/usr/bin/env python3`, so a commit with no python3 on PATH was
  refused (a GUI client, cron, or Windows where python3 is the Store's alias; python.org
  installs no python3.exe). CI missed it because `actions/setup-python` creates a
  `python3.exe` on Windows. The hook is now a sh wrapper running `commit-msg.py` with the
  installer's Python by absolute path, and it never blocks a commit.

## CI pitfalls

- pull.py's "Cloning ..." status goes to a terminal only; a clone is told apart by the missing
  "Using repository:" line, which only a `--repo` checkout prints.
- On Windows a Python-less PATH for git is Git's `cmd` dir plus its `usr\bin` (where the sh
  that runs hooks lives; neither holds a Python). `cmd\git.exe` adds `usr\bin` itself, but not
  when `MSYSTEM` is set, as under Git Bash; without it git says "cannot spawn .../commit-msg".
  Find the cmd dir by walking up from `which git` (bash finds `Git\bin\git.exe`).
- A batch file is read in the console's current code page, which is not the OEM one on the
  runner: write `.cmd` files in ASCII and reach non-ASCII dirs through `%USERPROFILE%` etc.
- GitHub push protection rejects WakaTime-key-shaped test values (`waka_<uuid>`); use a plain
  `ci-test-value-not-a-token`, which the installer accepts.

## Writing tests that pass on Windows (`tests/support.py`)

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

## Still not covered

- The real Microsoft Store `python3` alias: Windows Server runners have no Store. The hook no
  longer depends on PATH, and the Python-less commit covers the same failure.
- `claude plugin disable ccfa-skills@synced`: needs a plugin synced from a claude.ai account.
- agy running a hook itself, and so how it quotes the command for `cmd /c` on Windows: agy runs
  hooks only when logged in. Checked by hand on Linux with a real turn (rules applied, message
  delivered); the Windows command is a bare relative path to stay out of quoting.
- Tokscale itself: only its config dir is created.
- A Windows host in a CJK locale (code page 936 and the like) and a CJK user name.

## Known flake

The install checks follow upstream skill repos live. If one gets a commit during a job (seen
once: ui-ux-pro-max, between the first and second gateway install), the rerun updates that
skill and the "a second install changed ..." checks fail. Rerun the job; the installer did the
right thing.
