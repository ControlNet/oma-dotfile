# Tokscale submits Claude Opus 5.5 at $0 (2026-09-29)

## Symptom

tokscale.ai showed `claude-opus-5-5` usage with zero cost, although local `tokscale models` priced it (about $4/$20 per million input/output tokens via LiteLLM).

## Root cause

- Autosubmit (systemd, 2h interval) runs a copy of the binary kept at `~/.config/tokscale/autosubmit/tokscale`. That copy is **4.15.1**, frozen when autosubmit was enabled on 2026-09-09. Upgrading the `bunx` package does not update it.
- On submit, 4.15.1 rejects the `anthropic` + `claude-opus-5-5` price match with `model price match does not establish the requested provider` (upstream `ResolutionKind::ModelPart/ProviderPrefix` -> `SubmissionSafetyGap::UnverifiedProviderIdentity`, `crates/tokscale-core/src/pricing/lookup.rs`). Those messages are submitted with tokens only and cost 0, and the affected days are flagged cost-incomplete.
- Local reports use a looser path, so `tokscale models` and `tokscale pricing claude-opus-5-5` both show a price. Look for the real submit-time diagnosis in `~/.config/tokscale/autosubmit/autosubmit.log` or `tokscale submit --dry-run`.

## Evidence

- `~/.config/tokscale/autosubmit/tokscale submit --dry-run -c claude`: warns about 3369 unpriced `anthropic/claude-opus-5-5` messages; total $1560.12.
- `bunx tokscale@4.17.0 submit --dry-run -c claude`: no warning, same token count, total $1804.96 (the gap is Opus 5.5).
- Under 4.17.0, the remaining unpriced rows are unrelated legacy IDs: `github_copilot/*`, `azure/gpt-5.2-codex`, and `opencode/union-alpha`.

## Fix

Re-enable autosubmit using the newer CLI so it replaces the pinned binary, then submit again. The server keeps the higher total for days already marked cost-incomplete.

```bash
bunx tokscale@latest autosubmit enable --interval 2h
~/.config/tokscale/autosubmit/tokscale --version   # expect >= 4.17.0
bunx tokscale@latest submit --dry-run               # expect no claude-opus-5-5 warning
bunx tokscale@latest submit
```

A fallback that works on any version is an exact entry in `~/.config/tokscale/custom-pricing.json`, keyed by the bare model ID.
