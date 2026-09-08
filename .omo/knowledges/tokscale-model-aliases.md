# Tokscale model aliases

- Inspected local Tokscale 4.15.1 on 2026-09-08. It is available in the Bun package cache, although `tokscale` is not on this shell's PATH; `bunx tokscale` is the normal launcher.
- `tokscale_model_alias.json` contains a flat alias-to-upstream-model-ID map. It covers the repository's OpenCode/OMP GPT catalog and prefixed OpenAI/Anthropic IDs from the local usage report. Bare canonical IDs already group naturally. Unknown model identities are intentionally not inferred.
- `pull.py` merges the map into `settings.json.modelAliases`; repository entries win identical-key collisions, unrelated aliases/settings survive, unchanged files are skipped, and existing backup controls apply. Invalid source/settings structures warn without overwriting the destination.
- Config resolution follows `TOKSCALE_CONFIG_DIR`, Linux `XDG_CONFIG_HOME`, Windows `APPDATA`, and the default `~/.config/tokscale` on Linux/macOS.
- Upstream inspected at commit `15516420f2b106750760f6e182559899f814e2dc`: https://github.com/junhoyeo/tokscale/blob/15516420f2b106750760f6e182559899f814e2dc/crates/tokscale-core/src/model_alias.rs
- Aliases operate at local report grouping time, after cost calculation. They do not rewrite client/provider identity or export/submission IDs. Matching is case/separator insensitive and single-hop, with a 4096-entry cap; aliases do not support wildcard provider prefixes.
- Important compatibility limitation: `model_name_for_grouping` in `crates/tokscale-core/src/lib.rs` gives OpenCode's configured display name precedence over aliases. Confirmed with the installed binary: mapping `GPT 6 Astra (OAuth)` to `gpt-6-astra` leaves the OpenCode label intact. Changing the raw ID's alias affects Codex's row but still does not affect the OpenCode label.
- A temporary `OPENCODE_CONFIG_CONTENT` override setting the seven configured model names to their IDs proved the fix against real historical data through 2026-09-07: model rows decreased from 29 to 23, with identical token/message totals and cost (floating-point tolerance 0.000001). The real user's OpenCode and Tokscale settings were not changed. Live current-day reports cannot be compared for exact totals while agents continue writing sessions.
- The user chose to remove model-level `name` fields from repository `opencode.jsonc`. All seven GPT model labels were removed; the provider-level `name` remains. OpenCode's picker now falls back to model IDs, and Tokscale can use its normal ID/alias grouping after the updated OpenCode config is installed. Local user configuration has not been modified by this repository edit.

## Verification

Tests use synthetic settings only inside temporary directories, with Python's standard library:

```bash
python3 -m unittest discover -s tests -p 'test_tokscale_model_aliases.py'
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m json.tool tokscale_model_alias.json > /dev/null
git diff --check
```

Expected: 7 focused tests pass; JSON parses and no whitespace errors appear. The isolated staged snapshot passed all 15 Python tests plus `python3 -m py_compile pull.py`. The full working tree passed 30 tests, including unrelated, uncommitted Claude notification tests; those changes are excluded from this commit.

## OAuth label cleanup (2026-09-09)

Removed 70 obsolete OAuth display-name aliases, including provider-prefixed variants; retained all 150 model-ID aliases unchanged. OpenCode no longer configures model labels, and the observed OMP report uses model IDs. Updated the existing coverage test and README. The installer remains an additive merge: previously installed label aliases are harmless but are not automatically removed from user settings by this source-file cleanup.
