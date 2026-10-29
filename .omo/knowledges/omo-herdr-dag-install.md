# omo-herdr-dag install options (checked 2026-10-18, v1.7.0, omo 5.1.35)

Upstream: https://github.com/jc01rho/omo-herdr-dag (MIT, npm `omo-herdr-dag`, latest
1.7.0 published 2026-10-05). It is an OMO Native extension that draws live workflow
DAGs in a Herdr side pane. It does nothing unless OMO runs inside a Herdr pane
(`herdrSession()` checks the Herdr env), and it needs `herdr` on PATH and Node >= 24
for the viewer.

## What the upstream installer does

`omo-herdr-dag install [--agent-dir P] [--lang en|ko|zh-cn] [--dry-run]`
(`dist/scripts/install.mjs`):

- Agent dir: `--agent-dir`, then `OMO_CODING_AGENT_DIR`, then `SENPI_CODING_AGENT_DIR`,
  then `~/.omo/agent`. It does not read `PI_CODING_AGENT_DIR`, unlike omo.
- It writes only inside the agent dir:
  - `herdr-dag/integration/generation-NNNNNN/` (extension.mjs, src/, LICENSE, locale.json)
  - `herdr-dag/integration/current.json`
  - `extensions/omo-herdr-dag.js`, a one-line re-export wrapper starting with
    `// managed by omo-herdr-dag`
- **Every run creates a new generation and keeps the old ones** (no cleanup), so a
  blind rerun on each `pull.py` would pile them up.
- `--lang` is saved in the generation's `locale.json`; later runs without `--lang` keep it.
- It refuses to overwrite an unmanaged `extensions/omo-herdr-dag.js` or an unmanaged
  integration dir.
- No version is recorded in the install. To detect the installed version, compare
  `dist/extension.mjs` + `dist/src/` from the package with the current generation.

## Options

| Option | Verdict |
|---|---|
| senpi `packages: ["npm:omo-herdr-dag"]` in settings.json | Does not work: package.json has no `pi` manifest and no top-level `extensions/` dir, so senpi's package manager finds no extension (`core/package-manager.js` `resolveExtensionEntries`). |
| `npx omo-herdr-dag@X install` on every pull | Works, but adds a generation per run and can prompt without `--yes`. |
| Vendor the files into this repo | No: copies third-party code and bypasses its generation layout. |
| `npm pack omo-herdr-dag@<pinned>`, compare with the current generation, run the package's own `bin/omo-herdr-dag.mjs install --agent-dir <omo agent dir>` only when different | Recommended: pinned and idempotent, and it uses upstream's installer. |

## Nothing cleans up old generations (checked 2026-10-18)

- The plugin's `OMO_HERDR_DAG_RETENTION_DAYS` pruning (`src/retention.mjs`, default 14
  days) only deletes `*.json` / `*.tmp` files directly in the state dir
  (`~/.omo/agent/herdr-dag/`). It never touches `integration/generation-*`.
- omo 5.1.35 / senpi 2026.10.16: neither `omo-ai/bin`, `omo-ai/plugin` nor senpi `dist`
  mentions `herdr-dag` or `generation-`. `omo host gc` removes only dead host endpoints.
  Senpi's builtin `herdr` extension handles agent presence reporting and does no file
  cleanup.
- So every `install` run adds about 124K that stays until removed by hand. Deleting a
  non-current generation is safe for new sessions, but a session already running may
  still have that generation's modules loaded.

## Implemented in pull.py (2026-10-29)

Step 4 (OMO Native) calls `ensure_omo_herdr_dag` after the settings:

- Skipped unless `herdr`, `node` and `npm` are found (`find_agent_executable`, so nvm and
  per-user bin dirs count). The extension is inert outside a Herdr pane anyway.
- `npm pack omo-herdr-dag@<OMO_HERDR_DAG_VERSION> --json` into the run's temp dir. The
  tarball is extracted only if every member is a file or dir under `package/` without
  `..`; `filter="data"` is used when the Python has it.
- `herdr_dag_install_state` compares `dist/{extension.mjs,LICENSE,src/**}` byte for byte
  with the generation named in `current.json`, and checks that the wrapper carries the
  marker and imports that generation. `current` -> nothing runs, so no new generation;
  `missing`/`stale` -> `node <pkg>/bin/omo-herdr-dag.mjs install --agent-dir <omo agent dir>`;
  `unmanaged` (hand-written wrapper or integration dir without `.installed-by`) -> warn
  and skip, as the installer itself would refuse.
- `--agent-dir` is always passed because upstream ignores `PI_CODING_AGENT_DIR`, which
  `get_omo_agent_dir` honors.
- No `--lang`: a first install is English and later installs keep `locale.json`, so a
  one-time manual `install --lang zh-cn` survives updates.
- Not handled: pruning old generations (only grows on a version bump now) and the
  viewer's Node >= 24 requirement, which the installer does not check either.
- To upgrade, bump `OMO_HERDR_DAG_VERSION` after reading the release's install.mjs
  for layout changes (generation dir, wrapper text, marker).
