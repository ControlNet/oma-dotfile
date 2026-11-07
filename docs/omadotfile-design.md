# omadotfile: design for splitting pull.py into a package

Status: decided, not started. `pull.py` is about 2240 lines in one file. Each function is small; the
problem is that everything about one agent is spread over several places, global state is read
at import time, and generic helpers sit between agent-specific code. This document describes the
target layout and the order in which to get there without breaking installs.

## Invariants

These hold after every commit on `master`, since every machine installs from raw `master`:

- `curl -fsSL …/pull.py | python3` and the PowerShell one-liner keep working, with the same
  arguments (`--oauth`, `--all`) and environment variables.
- Python 3.10 or newer (Ubuntu 22.04's `python3`), standard library only.
- Windows and macOS branches stay (`sys.platform` checks in directory resolution).
- The same files land in the same places with the same content. Output text may change only
  where listed under [Behaviour changes](#behaviour-changes).

## Layout

```
pull.py                    bootstrap only (~60 lines), see below
omadotfile/
  __init__.py
  __main__.py              `python3 -m omadotfile --repo .` for local runs
  cli.py                   parse_args, main(argv, repo, source): banner, detection, steps, summary
  constants.py             what gets installed: agents, file lists, skills, pins, plugin ids
  context.py               Options, RepoRef, Context
  console.py               info / success / warn / error, banner, step header
  migration.py             @migration decorator and its registry (metadata only)
  core/                    knows nothing about any agent
    files.py               Files: write_text / copy / replace_tree / copy_items / retire, backups
    jsonc.py               read_jsonc_object, top-level object spans, model prefix rewrite
    toml_edit.py           facade over the line-based TOML editing helpers
    ini.py                 set keys in an INI section (WakaTime cfg)
    proc.py                find_executable, Cli (run a command, read its JSON)
  agents/
    base.py                Component, Agent, FileSpec
    opencode.py            config files, oauth provider merge, plugins/, legacy renames
    omo.py                 omo.jsonc shared by the OpenCode plugin and OMO Native
    omo_native.py          AGENTS.md, models.json, settings.json, omo-herdr-dag
    omp.py                 config, AGENTS.md, extensions, models.yml
    codex.py               AGENTS.md, notifier, config.toml
    claude.py              rules, plugins, attribution setting, commit-msg hook
    tokscale.py            model aliases
  features/                steps that span several agents
    wakatime.py            cfg + plugin installs through two CLI adapters
    skills.py              shared skills through the skills CLI
```

Rough sizes after the split: `toml_edit.py` and `codex.py` about 300 lines each, everything else
under 250.

## Core types

```python
@dataclass(frozen=True)
class Options:              # from argv and env, read once in cli.py
    oauth: bool
    install_all: bool
    backup: bool            # NO_BACKUP=1 -> False
    max_backups: int        # MAX_BACKUPS, default 1

@dataclass(frozen=True)
class RepoRef:              # which repo the skills CLI installs this repo's skills from
    owner: str = "ControlNet"
    name: str = "oma-dotfile"
    rev: str = "master"

@dataclass(frozen=True)
class Context:
    repo: Path              # checkout to install from (temp clone, or --repo)
    source: RepoRef
    work: Path              # scratch dir for downloads (npm pack, ...)
    stamp: str              # backup suffix
    options: Options
    env: Mapping[str, str]  # snapshot of os.environ
    home: Path
    found: frozenset[str]   # detected agent keys
    dirs: Mapping[str, Path]  # each agent's config dir, resolved once
    files: Files            # writes with this run's backup policy
```

Everything a function needs comes from its arguments. Module-level `NO_BACKUP`, `INSTALL_ALL`,
`CONFIG_DIR_ENV`, … go away, and so does reading `os.environ` deep inside helpers: tests build a
`Context` instead of patching globals.

`RepoRef` stays needed with `--repo .`: the skills CLI fetches this repo's own skills from GitHub
(`ControlNet/oma-dotfile#master`), not from the local checkout. It defaults to the `REPO_OWNER`,
`REPO_NAME` and `REPO_REV` environment variables, as today.

### Files: one place that writes

```python
class Files:
    def write_text(self, dst: Path, content: str, *, backup: bool = True, mode: int | None = None) -> bool
    def copy(self, src: Path, dst: Path, *, backup: bool = True) -> bool
    def replace_tree(self, src: Path, dst: Path) -> None
    def copy_items(self, src: Path, dst: Path) -> None
    def retire(self, path: Path) -> None       # today's rename_path_if_exists
```

Each call compares first and writes only on change; `backup` follows `Options.backup` and keeps
`max_backups` copies. Today the compare-backup-write sequence is written out separately in
`backup_and_install`, `install_managed_file`, `install_rendered_text`, `ensure_claude_attribution`,
`ensure_codex_config`, `install_tokscale_model_aliases` and the commit-msg hook. `Files` also
records what it changed, which the idempotence test below uses.

Content is computed by plain functions (`str -> str` or `dict -> dict`) that do no I/O, such as
today's `render_omo_oauth_config`, `render_omp_models`, `render_wakatime_config`. New code follows
the same split: compute in a pure function, write through `Files`.

### Components and agents

```python
class Component:                     # one numbered step
    title: str
    def enabled(self, ctx: Context) -> bool
    def skip_reason(self, ctx: Context) -> str
    def run(self, ctx: Context) -> None

@dataclass(frozen=True)
class FileSpec:                      # pure data, declared in constants.py
    src: str                         # path in the repo
    dst: str                         # path under the agent's dir
    managed: bool = False            # repo-owned code: no backup, else user config with backup

class Agent(Component):
    key: ClassVar[str]               # "codex"
    label: ClassVar[str]             # "Codex"
    executable: ClassVar[str | None]
    files: ClassVar[tuple[FileSpec, ...]] = ()

    @classmethod
    def config_dir(cls, env: Mapping[str, str], home: Path) -> Path
    def detect(self, env, home) -> bool            # default: executable found
    def enabled(self, ctx) -> bool                 # default: self.key in ctx.found
    def run(self, ctx) -> None                     # mkdir, install files, then configure()
    def configure(self, ctx, dir: Path) -> None    # agent-specific work; default nothing
```

`run` is a template method: it installs `files` the same way for every agent and then calls
`configure`, which only Codex, Claude, OMO Native and a few others override. Files whose content is
rewritten (the `--oauth` variants of `opencode.jsonc`, `omo.jsonc`, `omp_config.yml`, …) are left
out of `files` and written by `configure`, so `constants.py` holds no code. There is one
level of inheritance and no factories: the steps are a literal, ordered list in `cli.py`:

```python
AGENTS = (OpenCode(), OmoNative(), Omp(), Codex(), Claude(), Tokscale())   # detection order
STEPS = (AGENTS[0], OmoConfig(), AGENTS[1], AGENTS[2], AGENTS[3], WakaTime(),
         AGENTS[4], AGENTS[5], Skills())
```

Today's steps 2 and 5 (OpenCode files and plugins) become one step, as do 7 and 8 (Codex assets
and config.toml). The order is otherwise unchanged.

### WakaTime: one flow, two adapters

`ensure_codex_wakatime_plugin` and `ensure_claude_wakatime_plugin` (and their marketplace and
"is installed" helpers) are the same flow over two CLIs with different commands and JSON shapes.
`features/wakatime.py` gets a small adapter per CLI:

```python
class PluginCli(Protocol):
    agent: str                                         # "codex" / "claude"
    def plugin_state(self) -> PluginState              # missing / enabled / disabled
    def marketplace_source(self) -> str | None | Missing
    def add_marketplace(self) -> bool
    def install_plugin(self) -> bool
    after_install_hint: str
```

and one `ensure_plugin(cli)` that holds the flow and the messages once.

### Migrations

One-off cleanups (legacy config renames, old per-agent skill copies, retired and removed skills)
stay in the module that owns them, next to the code they clean up after. A decorator only records
metadata; it does not change what the function does:

```python
@migration(since="2026-04", reason="oh-my-opencode / oh-my-openagent config names", remove_by="2027-04")
def retire_legacy_openagent_files(ctx: Context, config_dir: Path) -> None: ...
```

- A migration runs on every install until its code is deleted. A machine that has not pulled for
  months still gets cleaned up.
- `tests/test_migrations.py` fails once any `remove_by` date has passed. That failing test is the
  only reminder; nothing is printed at install time. (The repo has no CI, so this shows up when the
  suite is run locally.)
- When it fails: delete the migration, or move `remove_by` later if some machine may still need it.

### Data: constants.py

`omadotfile/constants.py` holds what gets installed, as plain data with comments:

- repo defaults (`REPO_OWNER`, `REPO_NAME`, `REPO_REV`) and required environment variables;
- the agents: key, label, executable;
- each agent's `FileSpec` list;
- skill sources, skills excluded from Claude Code or disabled in Codex, retired and removed skills;
- pinned versions (skills CLI, omo-herdr-dag);
- WakaTime marketplace and plugin ids and URLs;
- legacy file names that migrations rename.

How things are installed stays with the code that does it: regexes for TOML/JSONC, marker strings,
timeouts and JSON field names live in their own modules. `constants.py` imports nothing from the
package, so every module can import it.

An external data file was ruled out: reading TOML needs `tomllib` (Python 3.11, not on Ubuntu
22.04), and JSON cannot carry the comments that explain most of these entries.

## Bootstrap contract (`pull.py`)

- Under `curl | python3` there is no script path (`__file__` is `<stdin>`), so the bootstrap
  cannot find a local checkout. It clones `REPO_OWNER/REPO_NAME@REPO_REV` into a temp dir unless
  `--repo PATH` is given.
- It handles only `--repo` and the `REPO_*` variables. All other arguments go unchanged to
  `omadotfile.cli.main(argv, repo=…, source=…)`, which owns `--oauth` / `--all` parsing.
- The temp clone lives until `main` returns. The clone dir is put first on `sys.path`, so an
  unrelated installed `omadotfile` cannot shadow it.
- It checks the Python version first and exits with one line on anything below 3.10.
- If the checkout has no `omadotfile/` (a `REPO_REV` older than the split), it exits with one line
  naming the revision instead of an `ImportError` traceback.

## Behaviour changes

Everything else must be identical:

1. Step numbering: 12 steps become 9 (merged OpenCode and Codex steps), numbered from the step
   list, and the clone message from the bootstrap has no number.
2. Message text stays the same except where a merged step needs one heading.

Error handling stays as it is: expected failures (unreadable config, bad JSON, a CLI that fails)
are caught where they happen, print `[WARN]` and the run goes on; an unexpected exception aborts
the run with a traceback; a failed clone or a missing required repo file exits 1.

## Migration plan

Each phase is one commit: full test suite green, golden run (below) unchanged, then push.

1. **Mechanical move.** `pull.py`'s body goes verbatim into `omadotfile/legacy.py`; `pull.py`
   becomes the bootstrap; `omadotfile/__main__.py` added. Tests import `omadotfile.legacy` instead
   of `pull.py`. No logic changes.
2. **Core.** `console`, `core/files.py` (`Files`), `jsonc`, `toml_edit`, `ini`, `proc`, and
   `Context`/`Options`. Globals removed. `legacy.py` calls into them.
3. **Agents.** `agents/base.py` and one module per agent; `cli.py` with the step list replaces
   `main`. `legacy.py` shrinks to features and migrations.
4. **Features.** `features/wakatime.py` (with the adapters) and `features/skills.py`; the
   migration decorator; `legacy.py` deleted.
5. **Wrap-up.** Idempotence test, migration date test, README and knowledge notes.

### Golden run

Install with the old `pull.py` (last commit before phase 1) and with the new code into two
sandboxes, then diff the trees. Backup files and other timestamps are ignored. Each sandbox needs:

- `HOME=<sandbox>`: `~/.omo`, `~/.agents/skills` and several defaults come from `Path.home()`
  without an environment override.
- `GIT_CONFIG_GLOBAL=<sandbox>/.gitconfig` and `GIT_CONFIG_NOSYSTEM=1`: the commit-msg hook sets
  `core.hooksPath` in the global git config.
- `XDG_STATE_HOME=<sandbox>/state`: the skills CLI lock.
- `--all`, and the `CODEX_BASE_URL` etc. variables set to fixed fake values.
- External commands (`npx skills`, `git ls-remote`, `npm pack`, `codex plugin`, `claude plugin`)
  run through stub scripts put first on `PATH` that record their arguments, so both runs see the
  same answers without network. One real install is done at the end.

### Test migration

- 13 test files load `pull.py` with `importlib`. In phase 1 they load `omadotfile.legacy`; later
  each test imports the module it covers.
- `patch.object(pull, "NO_BACKUP")` (14 uses), `INSTALL_ALL`, `MAX_BACKUPS`: build
  `Options(...)` in the test instead.
- `patch.object(pull.shutil, "which")` (15 uses): patch it in `omadotfile.core.proc`.
- `patch.object(pull.subprocess, "run")` used to fake `git clone` in `test_target_detection` and
  `test_pull_oauth`: no longer needed, since `cli.main` takes the repo path. The bootstrap gets its
  own small test.
- `detect_targets` / `report_targets` move with the agent list into `cli.py`.
- A shared `tests/support.py` provides `make_context(tmp, **overrides)`.
- New: an idempotence test that runs every step twice in a sandbox with stub CLIs and checks that
  `Files` changed nothing the second time.

## Decisions (2026-11-07)

- Error handling stays as it is today; no per-step isolation.
- Migrations keep running until deleted; a test fails after `remove_by`; no install-time reminder.
- Installer data goes in `constants.py`, limited to what gets installed.
- The cleanups for the chain hooks and the strip-attribution plugin were deleted before the split,
  since no machine has those states any more.
- Golden runs use stub CLIs.
