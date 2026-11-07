# OMP config.yml is merged, not replaced

oh-my-pi writes to `~/.omp/agent/config.yml` itself: `/settings` changes, consent keys such as
`dev.autoqaConsent: granted`, and it re-serializes values (bare `off` becomes `"off"`). When the
installer replaced the file with `omp_config.yml`, every pull dropped those keys and, because
the text never matched, rewrote the file and left a `.bak-*` each time.

Now `FileSpec("omp_config.yml", "config.yml", oauth=True, merge=True)` goes through
`Omp.install_merged_file` and `omadotfile/core/yaml_merge.py`:

- Repo keys win; keys only on disk are kept in place; new repo keys go last.
- A top-level block that is a flat `key: value` mapping on both sides merges key by key
  (OMP's additions under e.g. `tui:` survive). Lists, nested mappings and scalars come whole
  from the repo.
- Stdlib only, so it is line based. Flow style, block scalars (`|`, `>`), anchors, document
  markers or tabs make the file unsupported: it is then replaced, with a warning and a backup.
- If the merge changes nothing, the file is left as it is, even without a final newline (OMP
  writes none).
- `--oauth` rewrites `codex_api/` to `openai-codex/` before merging.
- `omp_config.yml` quotes `"off"` like OMP does; bare `off` is also false in YAML 1.1.
- A key deleted from `omp_config.yml` stays on machines that already have it; remove it with a
  one-off `@migration` if needed.

`opencode.jsonc`, `tui.json` and `omo.jsonc` stay replaced: on a machine in daily use they
were byte-identical to the installer's output, so OpenCode and OMO do not write them back.
