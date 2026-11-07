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
| `TARGET_LABELS`, `AGENT_EXECUTABLES`, file lists, `UPSTREAM_SKILLS`, pins, plugin ids | `constants.py` |
| `backup_and_install`, `install_managed_file`, `install_rendered_text`, `rename_path_if_exists`, `copy_directory*`, `cleanup_old_backups` | `core/files.py`: `Files.copy`, `write_text`, `retire`, `replace_tree`, `copy_items`, `prune` |
| `find_agent_executable`, `extra_bin_search_path`, `run_plugin_process`, `read_plugin_json` | `core/proc.py`: `find_executable`, `Runner.run`, `.ok`, `.json` |
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

Things worth knowing when changing it:

- Every write goes through `ctx.files` (`Files`): it compares first, writes only on change,
  backs up user config (`managed=False`) as `.bak-<stamp>`, and records `changed`.
  `tests/test_install_run.py` fails if a second install writes anything.
- An agent is a `Component` with `files` (`FileSpec` in `constants.py`) plus `configure`.
  A file with an `--oauth` variant is `FileSpec(..., oauth=True)` and the agent overrides
  `install_oauth_file`.
- The steps are the literal `STEPS` tuple in `cli.py`; their numbers come from its order.
- One-off cleanups are `@migration(since=, reason=, remove_by=)`. They run on every install
  until deleted; `tests/test_migrations.py` fails from the `remove_by` month on.
- PATH lookups (`shutil.which`) still read the process environment, not `ctx.env`; tests
  that need a fake PATH patch `os.environ` as well.
- Run the tests from the repo root: `python3 -m unittest discover -s tests` (the dotted
  `python3 -m unittest tests.test_x` form cannot import `tests/support.py`).
