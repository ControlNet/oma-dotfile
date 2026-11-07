# omadotfile: design for splitting pull.py into a package

Status: done (2026-11-07). `omadotfile/legacy.py` is gone; see [How it went](#how-it-went).

Before the split, `pull.py` was about 2240 lines in one file. Each function was small; the
problem was that everything about one agent was spread over several places, global state was read
at import time, and generic helpers sat between agent-specific code. This document describes the
layout and how the installer got there without breaking installs.

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
  __main__.py              `python3 -m omadotfile` from a checkout's root
  cli.py                   parse_args, main(argv, repo, env, home): banner, detection, steps, summary
  constants.py             what gets installed: agents, file lists, skills, pins, plugin ids
  context.py               Options, RepoRef, Context
  console.py               info / success / warn / error, banner, step header
  migration.py             @migration decorator and its registry (metadata only)
  core/                    knows nothing about any agent
    files.py               Files: write_text / copy / replace_tree / copy_items / retire, backups
    jsonc.py               read_jsonc_object, top-level object spans, model prefix rewrite
    toml_edit.py           facade over the line-based TOML editing helpers
    ini.py                 set keys in an INI section (WakaTime cfg)
    proc.py                find_executable, Runner (run a command, read its JSON)
  agents/
    base.py                Component, Agent (FileSpec is in constants.py)
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
    files: Files            # cached property: writes with this run's backup policy
    runner: Runner          # cached property: runs agent CLIs with this env and home
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
    def update(self, dst: Path, codec: Codec[T], transform: Callable[[T], T], *, default: T,
               backup: bool = True, mode: int | None = None) -> bool
```

`update` is the read-modify-write every merged config goes through: it loads dst with a
`Codec` (`core/codec.py`: `JSON`, `JSONC`, `LINES`, `TEXT`; `Codec[T]` is a Protocol with
`load` and `dump`), applies a pure `transform`, and writes only when the value changed. A
transform is usually a module-level function with its fixed arguments bound by
`functools.partial`, e.g. `partial(with_extension_disabled, "rules")`, or a closure built by a
function such as `codex.config_transform(ctx, codex_dir)`.

Each call compares first and writes only on change; `backup` follows `Options.backup` and keeps
`max_backups` copies. Today the compare-backup-write sequence is written out separately in
`backup_and_install`, `install_managed_file`, `install_rendered_text`, `ensure_claude_attribution`,
`ensure_codex_config`, `install_tokscale_model_aliases` and the commit-msg hook. `Files` also
records what it changed, which the idempotence test below uses.

Content is computed by plain functions (`str -> str` or `dict -> dict`) that do no I/O, such as
today's `render_omo_oauth_config`, `render_omp_models`, `render_wakatime_config`. New code follows
the same split: compute in a pure function, write through `Files`.

### Steps, components and agents

```python
class Step(Protocol):                # omadotfile/step.py: one numbered step
    def title(self, ctx: Context) -> str
    def enabled(self, ctx: Context) -> bool
    def skip_reason(self, ctx: Context) -> str
    def run(self, ctx: Context) -> None

@step("Configuring WakaTime config and plugins", when=found_any("opencode", "omp", "codex", "claude"),
      skip="no WakaTime-tracked agent found")
def configure_wakatime(ctx: Context) -> None: ...   # becomes a FunctionStep (a frozen dataclass)

class Component:                     # a Step that installs `files` under target_dir, then configure()

@dataclass(frozen=True)
class FileSpec:                      # pure data, declared in constants.py
    src: str                         # path in the repo
    dst: str                         # path under the agent's dir
    managed: bool = False            # repo-owned code: no backup, else user config with backup
    oauth: bool = False              # under --oauth the agent's install_oauth_file writes it

class Agent(Component):
    key: ClassVar[str]               # "codex"
    label: ClassVar[str]             # "Codex"
    executable: ClassVar[str | None]
    files: ClassVar[tuple[FileSpec, ...]] = ()

    @staticmethod
    def config_dir(env: Mapping[str, str], home: Path) -> Path
    def detect(self, env, home) -> bool            # default: executable found
    def enabled(self, ctx) -> bool                 # default: self.key in ctx.found
    def run(self, ctx) -> None                     # mkdir, install files, then configure()
    def configure(self, ctx, dir: Path) -> None    # agent-specific work; default nothing
```

`run` is a template method: it installs `files` the same way for every agent and then calls
`configure`, which only Codex, Claude, OMO Native and a few others override. Files with an
`--oauth` variant (`opencode.jsonc`, `omo.jsonc`, `omp_config.yml`) are marked `oauth=True`; under
`--oauth` the agent's `install_oauth_file` writes the rewritten copy, so `constants.py` holds no
code.

`Step` is a Protocol, so a step is anything with those four methods: the agent classes
inherit them from `Component` (inheritance only for the shared template method), and the two
steps that install no files, WakaTime and shared skills, are functions made into steps by
`@step`. `found_any(*keys)` returns the predicate closure they run under. A method that does
not use `self` is a `@staticmethod` (`config_dir`, `configure`, `install_oauth_file`,
`install_merged_file`, the codecs' `load`/`dump`), declared static in the base class too so
overrides type-check; `title`, `enabled`, `skip_reason` and `target_dir` stay instance methods
because `Agent`'s versions read `self`. `@classmethod` builds instances (`Options.from_env`,
`RepoRef.from_env`). There are no factories: the steps are a literal, ordered tuple in `cli.py`:

```python
STEPS: tuple[Step, ...] = (AGENTS["opencode"], OmoConfig(), AGENTS["omo"], AGENTS["omp"],
                           AGENTS["codex"], configure_wakatime, AGENTS["claude"],
                           AGENTS["tokscale"], install_shared_skills)
```

Today's steps 2 and 5 (OpenCode files and plugins) become one step, as do 7 and 8 (Codex assets
and config.toml). The order is otherwise unchanged.

### WakaTime: one flow, two adapters

`ensure_codex_wakatime_plugin` and `ensure_claude_wakatime_plugin` (and their marketplace and
"is installed" helpers) are the same flow over two CLIs with different commands and JSON shapes.
`features/wakatime.py` gets a small adapter per CLI:

```python
class PluginCli:                     # CodexPlugins, ClaudePlugins
    label: str                       # "Codex" / "Claude Code"
    executable: str
    dir_env: str                     # CODEX_HOME / CLAUDE_CONFIG_DIR, pinned to the installer's
    plugin_id: str
    after_install: str
    def is_installed(self) -> bool   # warns when installed but disabled
    def ensure_marketplace(self) -> bool
    def install(self) -> bool
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
  `omadotfile.cli.main(argv, repo=…)`, which owns `--oauth` / `--all` parsing and reads
  `REPO_*` again for the skills source.
- The temp clone lives until `main` returns. The clone dir is put first on `sys.path`, so an
  unrelated installed `omadotfile` cannot shadow it.
- It checks the Python version first and exits with one line on anything below 3.10.
- If the checkout has no `omadotfile/` (a `REPO_REV` older than the split), it exits with one line
  naming the revision instead of an `ImportError` traceback.

## Behaviour changes

Everything else must be identical:

1. Step numbering: 12 steps become 9 (merged OpenCode and Codex steps), numbered from the step
   list. The clone message from the bootstrap and `Using repository: …` have no number.
2. Message text stays the same except where a merged step needs one heading, and file lines,
   which now print `src -> dst` whenever the names differ (`_AGENTS.md -> AGENTS.md`).
3. An unchanged file is no longer rewritten or backed up; only files whose content changes get a
   `.bak-<stamp>`.
4. `__pycache__` in a local checkout is no longer copied into the Claude Code plugin dir.

Error handling stays as it is: expected failures (unreadable config, bad JSON, a CLI that fails)
print `[WARN]` and the run goes on; an unexpected exception aborts the run with a traceback; a
failed clone or a missing required repo file exits 1. Inside, pure helpers raise (`ValueError`
for bad content); the function that does one install action is decorated with
`@warns_on(OSError, ValueError, message="Failed to read {dst} ({error}); ...")`
(`core/errors.py`), which turns exactly those errors into the warning and returns None. The
message fields are checked against the function's parameters when the module is imported.

## Migration plan

As planned, each phase was one commit: full test suite green, golden run (below) unchanged, then
push. Phases 2 to 5 ended up as one commit (see [How it went](#how-it-went)).

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

## How it went

- Phase 1 was its own commit. Phases 2 to 5 were done as one port instead of moving code out of
  `legacy.py` piece by piece: every module was written against `Context`, then `cli.py` replaced
  `legacy.main`, the tests were ported module by module, and `legacy.py` was deleted.
- Golden runs against `legacy.main` matched file for file, apart from the changes listed under
  [Behaviour changes](#behaviour-changes), in four sandboxes: `--all` with no agent CLIs; every
  agent detected through stub CLIs (the stubs' recorded calls matched too); `--oauth --all`; and
  existing user config with backups on (`opencode.json`, `oh-my-opencode.json`, `~/.omo/config.json`,
  a user `config.toml`, Claude `settings.json`, Tokscale aliases, `.wakatime.cfg`).
- `tests/test_install_run.py` runs `cli.main` twice with stub `codex`, `claude` and `npx`, and
  checks that the second run changes no file, makes no backup and re-adds nothing.
- Tests run with `python3 -m unittest discover -s tests` from the repo root.

### Second pass: higher-order functions and decorators (2026-11-07)

- `@warns_on` replaced each hand-written try/except-warn block; `Files.update` with a `Codec`
  replaced the seven read-modify-write blocks (Claude settings, OMO Native settings and
  models, Tokscale, Codex config.toml, WakaTime cfg, OMP config.yml).
- WakaTime and shared skills became `@step` functions; `OmoConfig` stays a `Component`.
- Methods that never use `self` became `@staticmethod` through the whole hierarchy.
- Style choices, from the owner: decorators and closures yes; no `>>` pipe objects (they
  wreck tracebacks), no facade namespace objects, Protocols for interfaces.
- Types are checked with pyright (`pyrightconfig.json`: standard mode, strict for `step.py`,
  `core/errors.py`, `core/codec.py`, `core/yaml_merge.py`); `@warns_on` keeps the decorated
  function's signature through `ParamSpec` and adds `| None` to its return type.
- The suite runs on Python 3.10 to 3.14 (`pixi exec --spec python=3.X`); on 3.10, 21 tests
  that parse the written TOML with `tomllib` (or test a safeguard that needs it) are skipped
  by `@requires_tomllib`, and `support.TestCase` adds `enterContext` (Python 3.11+). A full
  sandboxed install under each version wrote the same files, apart from the interpreter path
  in Codex's `notify`.
- A golden run against the previous commit matched in four sandboxes (fresh, `--oauth`,
  existing config, two runs). The one output change: Tokscale now prints "Updated ...;
  preserved unrelated settings" after writing instead of "Updating ..." before it.

### Third pass: Skip, preconditions and folds (2026-11-07)

- `Skip` (`core/errors.py`) is the exception an install action raises to stop early; `@skips`
  (which is `warns_on(Skip, message="{reason}")`) prints its message verbatim. So
  `ensure_herdr_dag` reads as its happy path: `tarball_from_pack` (a `match` on the
  `npm pack --json` document) and `extract_npm_package` raise `Skip` instead of returning None,
  and the install state is an `InstallState` enum matched with `match`.
- `@requires("node", "npm", skip="...")` (`step.py`) guards an action that takes the Context
  first (`Concatenate[Context, P]`, so the signature survives); it looks executables up through
  `ctx.runner.which`. It replaced the hand-written checks in `ensure_herdr_dag` and
  `ensure_skills`. `ensure_plugin` keeps its own check: it takes a `PluginCli`, not a Context.
- `ensure_skills` is plan, execute, fold: a closure `install_or_reuse(install) -> InstallResult`
  runs once per skills CLI run, and the pure `recorded_commits(results)` is the new commit
  record. Every run of this install has a result, so dropped runs leave the record without the
  old "filter to active keys" step. `legacy_copy_names` is the pure half of the migration.
- Small pure extractions: `wakatime.settings_from_env`, `omp.oauth_models` /
  `gateway_models` / `write_models` (each with `@warns_on`; writing the OAuth catalog now warns
  on OSError instead of aborting), `cli.done_notes`.
- Not done, on purpose: `Runner` raising `CommandFailed` instead of returning None, and a
  `Runner.pinned(**env)` closure. Tests patch `Runner.json`/`Runner.ok` on the class and read
  the `extra_env` they get, and the golden run only covers the success path, so that change
  needs its own pass with failure-path tests first.
- Typeclasses and monads were evaluated with pyright probes. A `Result`/`Either` type was
  rejected: on 3.10 there is no `typing.Never`, so `Err.map`/`Err.bind` need `NoReturn` or
  `Any` parameters, lambdas in `.map(...)` chains come out partially `Unknown` under strict
  mode, and an `Err(exc)` that is never raised has no traceback. `T | None` already is Option,
  and closures over `ctx` already are Reader. Worth doing later: `@abstractmethod` on
  `Component`/`Agent`/`PluginCli` (pyright then reports a missing method at instantiation),
  and a `Codec.empty()` so `Files.update` needs no `default=`.
