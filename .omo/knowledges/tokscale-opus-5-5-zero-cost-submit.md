# Tokscale submits Claude Opus 5.5 at $0 (2026-09-29)

## Symptom

tokscale.ai showed `claude-opus-5-5` usage with zero cost, although local `tokscale models` priced it (about $4/$20 per million input/output tokens via LiteLLM).

## Root cause

- Autosubmit (systemd, 2h interval) runs a copy of the binary kept at `~/.config/tokscale/autosubmit/tokscale`. That copy is **4.15.1**, frozen when autosubmit was enabled on 2026-09-09. Upgrading the `bunx` package does not update it.
- On submit, 4.15.1 rejects the `anthropic` + `claude-opus-5-5` price match with `model price match does not establish the requested provider` (upstream `ResolutionKind::ModelPart/ProviderPrefix` -> `SubmissionSafetyGap::UnverifiedProviderIdentity`, `crates/tokscale-core/src/pricing/lookup.rs`). Those messages are submitted with tokens only and cost 0, and the affected days are flagged cost-incomplete.
- Local reports use a looser path, so `tokscale models` and `tokscale pricing claude-opus-5-5` both show a price. Look for the real submit-time diagnosis in `~/.config/tokscale/autosubmit/autosubmit.log` or `tokscale submit --dry-run`.

## Evidence

- `~/.config/tokscale/autosubmit/tokscale submit --dry-run -c claude`: warns about unpriced `anthropic/claude-opus-5-5` messages.
- `bunx tokscale@4.17.0 submit --dry-run -c claude`: no warning, same token count, and a higher total (the gap is Opus 5.5).
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

## Follow-up (2026-10-02): re-enabling stopped the systemd timer

- Re-running `autosubmit enable` rewrites the units and restarts the timer. The timer only has
  `OnBootSec=5m` + `OnUnitActiveSec=120min`; after the reload the service has no activation
  timestamp, so `NextElapseUSecMonotonic=infinity` and the timer shows `active (elapsed)`,
  `Trigger: n/a` (seen on systemd 249). Autosubmit then silently stops.
- Detect: `systemctl --user list-timers | grep tokscale` shows NEXT `n/a`.
- Re-arm once: `systemctl --user start tokscale-autosubmit.service` (this submits).
- Durable: a timer drop-in with `OnActiveSec=5m` so a restarted timer always fires once.
- The 4.17.0 dry-run no longer lists `claude-opus-5-5` as unpriced; remaining
  unpriced rows are legacy `github_copilot/*`, `azure/gpt-5.2-codex`, `opencode/union-alpha`.
- Alternative without hand-editing systemd: `bunx tokscale@latest autosubmit enable --scheduler cron --interval 2h`.
  Per `crates/tokscale-cli/src/commands/autosubmit.rs`, `enable` uninstalls the previous scheduler
  itself (`systemctl --user disable --now` + removes the unit files), then writes a marked crontab
  block (`# BEGIN/END TOKSCALE AUTOSUBMIT`). For intervals >= 60 min cron runs hourly
  (`0 * * * *`) and `autosubmit run` submits only when due. Unrelated crontab lines are preserved.
- `scanner.extraScanPaths.senpi: ["~/.omo/agent/sessions"]` (tested via `TOKSCALE_EXTRA_DIRS`)
  finds the main OMO sessions but not task children, which extra paths do not discover (4.17.0).
- Caveats when using cron:
  - `enable` without `--scheduler` falls back to `default_scheduler_kind()`, which picks systemd
    when `systemctl` exists, so a plain re-enable silently returns to the stalling timer. Always
    pass `--scheduler cron`.
  - The managed binary is still a copy frozen at enable time; after a Tokscale upgrade re-run
    `bunx tokscale@latest autosubmit enable --scheduler cron --interval 2h`.
- Cron + `--interval 2h` actually submits every 3h: cron fires hourly at :00, the due check is
  `now < last_run + interval`, and `last_run_at_ms` is recorded when the submit finishes
  (`crates/tokscale-cli/src/main.rs`, `AutosubmitSubcommand::Run`), so at +2h the elapsed time is
  2h minus the submit duration and the run is skipped. Use `--interval 110m` (still hourly cron) to
  get an effective 2h, as long as one submit takes under 10 minutes (a full scan takes minutes).
- Other OSes (from source, not tested there):
  - Default scheduler: macOS launchd (`StartInterval` = interval seconds, `RunAtLoad`), Windows Task
    Scheduler (`/SC MINUTE /MO <interval>` under 24h), Linux systemd if `systemctl --user` works,
    else cron.
  - launchd and Task Scheduler fire every exact interval, so with the finish-time due check a 2h
    interval skips every other tick (effective ~4h). Use a slightly shorter interval, e.g. `115m`.
  - `--scheduler cron` on Windows fails (no `crontab`); on macOS it works but misses runs while
    asleep, so prefer the launchd default there.
