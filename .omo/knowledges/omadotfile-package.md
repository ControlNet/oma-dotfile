# omadotfile: where the old pull.py code went

In November 2026 the 2000+ line `pull.py` installer became the `omadotfile` package
(design and decisions: `docs/omadotfile-design.md`). `pull.py` is now only a bootstrap:
it clones `REPO_OWNER/REPO_NAME@REPO_REV` (or takes `--repo PATH`), puts the clone first on
`sys.path` and calls `omadotfile.cli.main(argv, repo=...)`. It keeps to Python 3.6 syntax
so that old interpreters reach its version check instead of a `SyntaxError`.

Older notes in this directory name `pull.py` functions. Where they live now:

| pull.py (before the split) | now |
|---|---|
| `main`, `parse_args`, `detect_targets`, `report_targets`, `warn_missing_required_env_vars` | `cli.py` (`main`, `parse_args`, `detect_agents`, `report_agents`, ...) |
| `NO_BACKUP`, `INSTALL_ALL`, `MAX_BACKUPS`, `REPO_*`, `*_DIR_ENV` globals | `context.py`: `Options`, `RepoRef`, `Context` (env snapshot, home, agent dirs) |
| `TARGET_LABELS`, `AGENT_EXECUTABLES` | class keywords `class Codex(Agent, key=..., label=..., executable=...)` (`Agent.__init_subclass__`); order in `cli.AGENTS` |
| file lists, `UPSTREAM_SKILLS`, pins, plugin ids | `constants.py` |
| `backup_and_install`, `install_managed_file`, `install_rendered_text`, `rename_path_if_exists`, `copy_directory*`, `cleanup_old_backups` | `core/files.py`: `Files.copy`, `write_text`, `retire`, `replace_tree`, `copy_items`, `prune` |
| `find_agent_executable`, `extra_bin_search_path`, `run_plugin_process`, `read_plugin_json` | `core/proc.py`: `find_executable`, `Runner.run`, `.json` (raise `CommandFailed`), `.pinned` |
| TOML helpers (`toml_*`, `replace_toml_section`, tomllib fallback) | `core/toml_edit.py` (`parses`, `loads` wrap tomllib) |
| JSONC helpers | `core/jsonc.py` |
| `render_wakatime_config` | `core/ini.py` `set_section_keys` + `features/wakatime.py` `render_config` |
| `get_config_dir` / `install_opencode_config_files` / legacy renames | `agents/opencode.py` |
| `install_omo_config`, `render_omo_oauth_config`, `retire_legacy_omo_files` | `agents/omo.py` |
| `get_omo_agent_dir`, `install_omo_native_models`, `ensure_omo_native_settings`, `ensure_omo_herdr_dag` | `agents/omo_native.py` |
| `get_omp_agent_dir`, `render_omp_models`, `backup_and_install_omp_models` | `agents/omp.py` |
| `ensure_codex_config` and the `ensure_codex_*` helpers | `agents/codex.py` (`ensure_config`, `ensure_api_provider`, ...) |
| `install_claude_plugins`, `ensure_claude_attribution`, `ensure_git_commit_msg_hook` | `agents/claude.py` |
| `install_tokscale_model_aliases`, `get_tokscale_config_dir` | `agents/tokscale.py` |
| `ensure_wakatime_config`, `ensure_*_wakatime_plugin` | `features/wakatime.py` (`ensure_config`, `CodexPlugins` / `ClaudePlugins` + `ensure_plugin`) |
| `ensure_agent_skills` and the skills helpers | `features/skills.py` (`ensure_skills`, ...) |

Repo layout: the installed files live under `config/` (one dir per agent, laid out like its
config dir). Older notes use the root names from before 2026-11-07:

| old root path | now |
|---|---|
| `_AGENTS.md` | `config/_AGENTS.md` |
| `opencode.jsonc`, `tui.json`, `plugins/` | `config/opencode/` (same names) |
| `omo.jsonc` | `config/omo/omo.jsonc` |
| `omp_config.yml`, `omp_models.yaml`, `omp_models_oauth.yaml` | `config/omp/config.yml`, `models.yml`, `models.oauth.yml` |
| `omp-gotify-notify.js`, `omp-wakatime-sync.js` | `config/omp/extensions/` (same names) |
| `codex-gotify-notify.py` | `config/codex/codex-gotify-notify.py` |
| `claude-plugins/` | `config/claude/plugins/` |
| `tokscale_model_alias.json` | `config/tokscale/model-aliases.json` |
| `git-hooks/commit-msg` | `config/git-hooks/commit-msg` |

Things worth knowing when changing it:

- Every write goes through `ctx.files` (`Files`): it compares first, writes only on change,
  backs up user config (`managed=False`) as `.bak-<stamp>`, and records `changed`.
  `tests/test_install_run.py` fails if a second install writes anything.
- An agent is a `Component` with `files` (`FileSpec` in `constants.py`) plus `configure`.
  A file with an `--oauth` variant is `FileSpec(..., oauth=True)` and the agent overrides
  `install_oauth_file`.
- A config the installer edits rather than replaces goes through
  `ctx.files.update(dst, codec, transform)`: `Codec` (`core/codec.py`) loads, dumps and gives
  `empty()` for a missing file; `transform` is a pure function (bind arguments with `functools.partial`). The function
  doing it is wrapped in `@warns_on(OSError, ValueError, message="...{dst}...({error})")`
  (`core/errors.py`) instead of a try/except; pure helpers just raise.
- An action that stops early raises `Skip("message")` (`core/errors.py`) and is decorated
  `@skips`, which prints the message verbatim as the [WARN] line; keep leading spaces in the
  message if the old output had them. Message texts are asserted in the tests.
- An action that needs a CLI is decorated `@requires("npx", skip="...")` (`step.py`); its
  first parameter must be the Context. It uses `ctx.runner.which`, so tests that patch
  `Runner.which` on the class still control it.
- `Runner.run`/`.json` raise `CommandFailed` (a `Skip`) on failure; there is no None result.
  An agent CLI gets `ctx.runner.pinned({"CODEX_HOME": ...})`. A caller that can go on without
  the result calls through a small `@skips` function (`PluginCli.listing`, `skills.add_skills`).
- Runner methods are patched on the class in the tests with `autospec=True`
  (`patch.object(Runner, "json", autospec=True, side_effect=fake)`), so the fake gets
  `(runner, command)` and can check `runner.pin`. A refactor that calls a new Runner method
  must update those patches; the skills and herdr harnesses also patch `subprocess.run` to
  raise, so a call that slips past the fakes fails instead of running real `npm`/`node`.
- A step that installs no files is a function decorated with `@step(title, when=found_any(...),
  skip=...)` (`omadotfile/step.py`); `Step` is a Protocol that agent classes also satisfy.
- Types: `pixi exec --spec pyright pyright` from the repo root (config in `pyrightconfig.json`)
  should report 0 errors.
- Supported Pythons are 3.10 to 3.14 (Ubuntu 22.04 ships 3.10). Run the suite on each with
  `for v in 3.10 3.11 3.12 3.13 3.14; do pixi exec --spec "python=$v" -- python -m unittest discover -s tests; done`.
  Test classes inherit `support.TestCase` (adds `enterContext` on 3.10); tests that need
  `tomllib` to check output carry `@requires_tomllib` and are skipped on 3.10.
- `Component`, `Agent` and `PluginCli` are ABCs; a method every subclass must define is an
  `@abstractmethod` (pyright then reports a subclass that leaves it out), not a
  `raise NotImplementedError` body.
- A method that never uses `self` is a `@staticmethod` (declared static in the base class as
  well, or pyright reports the override).
- A file the agent also writes to is `FileSpec(..., merge=True)`; the agent's
  `install_merged_file` merges it (OMP `config.yml`, see `omp-config-merge.md`).
- The steps are the literal `STEPS` tuple in `cli.py`; their numbers come from its order.
- A new agent is `class X(Agent, key="key", label="Name", executable="cli")` (all three
  keywords are required; pyright reports a missing one); add an instance to the `AGENTS`
  tuple in `cli.py`, whose order is the report order. Declaring the class registers nothing.
- Protocol vs ABC: a Protocol where implementations share no code (`Step`, `Codec`); an ABC
  where they share a template method (`Component`/`Agent`). Pyright does not see attributes a
  class decorator sets, so a decorator cannot make a class satisfy a Protocol.
- A function that needs only some services takes them as leading positional-only parameters
  under `@inject` (`def f(files: Files, runner: Runner, /, dst: Path)`; callers still pass `ctx`).
  Only `Files`/`Runner`/`Options`/`RepoRef` inject by type; for `Path`/`Mapping` fields use
  `@uses(home_of, repo_of)`. Put `@inject` above `@warns_on`. A new injectable type goes in both
  `PROVIDERS` and the `Dep1..3` constraints (a test checks they match). A TypeVar constrained to
  `Home = NewType("Home", Path)` accepts `Home` and rejects a plain `Path` in pyright, so a NewType
  would make `home` injectable by type if ever needed.
- `cli.main` is the composition root and the only reader of `os.environ`, `Path.home()`,
  `sys.platform` and `sys.executable`. Agents get the platform as a parameter
  (`config_dir(env, home, platform)`, `detect(env, home, platform)`); the interpreter for
  installed hooks and the Codex notifier is `ctx.python`. Context has no ambient defaults for
  `home`/`python` (only `stamp`, the clock). Check:
  `grep -rn 'os.environ\|sys.platform\|sys.executable\|Path.home()' omadotfile | grep -v cli.py`
  (comments only). git runs through `ctx.runner` like every other CLI: `run(..., check=False)`
  when a non-zero exit is an answer (`git config --get` of an unset key), `timeout=` per call.
- One-off cleanups are `@migration(since=, reason=, remove_by=)`. They run on every install
  until deleted; `tests/test_migrations.py` fails from the `remove_by` month on.
- PATH lookups read the run's env (`ctx.env["PATH"]`), never the process PATH:
  `proc.find_executable(name, env, home)` / `Runner.which` (PATH, then per-user bin dirs) to find
  an agent CLI, `proc.on_path(name, env)` / `Runner.on_path` (PATH only) for what a hook or
  shebang will find (`python3`, `node`). An env without PATH gets `os.defpath`: passing
  `path=None` to `shutil.which` would fall back to `os.environ`. Tests give a fake PATH through
  `env={"PATH": ...}` instead of patching `shutil.which`. Residue: on Windows `shutil.which`
  still reads `PATHEXT` from `os.environ`.
- Run the tests from the repo root: `python3 -m unittest discover -s tests` (the dotted
  `python3 -m unittest tests.test_x` form cannot import `tests/support.py`).
