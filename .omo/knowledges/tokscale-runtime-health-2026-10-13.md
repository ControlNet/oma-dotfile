# Tokscale autosubmit runtime health (checked 2026-10-13, tokscale 4.18.0)

How to tell whether autosubmit is really running, and what switching it to cron does.

## Stalled systemd timer

- Symptom: the timer is enabled and `active (elapsed)` but has no next firing:
  `NextElapseUSecMonotonic=infinity`, and `systemctl --user list-timers` shows NEXT and LEFT as
  `n/a`. The generated timer only has `OnBootSec=5m` and `OnUnitActiveSec=120min`, so once the
  service has no activation timestamp nothing re-arms it. `lastError` stays null and the log ends
  with a successful submit, so status alone does not prove scheduling still works; check that the
  last-run timestamp keeps advancing.
- Repair options: a timer drop-in with `OnActiveSec=5m` (fires once after every timer start), or
  move to cron (below). Starting the service by hand re-arms it but also uploads usage, so it is
  not a harmless diagnostic.

## `autosubmit enable` without `--scheduler`

`bunx tokscale@latest autosubmit enable --interval 2h` is valid, but in 4.18.0 omitting
`--scheduler` picks the detected platform backend every time; it does not remember an earlier
cron choice. On Linux, if `systemctl --user --version` succeeds, that backend is systemd. Sources:
[enable scheduler selection](https://github.com/junhoyeo/tokscale/blob/v4.18.0/crates/tokscale-cli/src/commands/autosubmit.rs#L201),
[default backend detection](https://github.com/junhoyeo/tokscale/blob/v4.18.0/crates/tokscale-cli/src/commands/autosubmit.rs#L717),
[generated timer](https://github.com/junhoyeo/tokscale/blob/v4.18.0/crates/tokscale-cli/src/commands/autosubmit.rs#L1035).

## Switching to cron

- `bunx tokscale@latest autosubmit enable --scheduler cron --interval 2h` removes the systemd
  service and timer itself, then writes a marked block that runs the managed binary's
  `autosubmit run` hourly (`0 * * * *`) and appends to the existing autosubmit log. Unrelated
  crontab lines are preserved.
- Back up `crontab -l` and `~/.config/tokscale/` first, with private permissions (0700 directory,
  0600 files), since the settings may hold the submit token.
- Hourly cron with a 2h interval submits roughly every 3h (finish-time due check, see
  `tokscale-opus-5-5-zero-cost-submit.md`); `--interval 110m` gives an effective 2h.
- This only fixes scheduling. OMO Native usage still needs the path override on 4.18.0 (see
  `tokscale-omo-session-path-support.md`), and the scheduled process must see it too: neither the
  systemd user manager nor cron inherits it from an interactive shell.

## Other checks

- `submit --dry-run` scans every client and uploads nothing; it is the safe way to confirm the
  scanner works.
- Legacy models such as `github_copilot/*`, `azure/gpt-5.2-codex` and `opencode/union-alpha` still
  get zero cost in 4.18.0. These are pricing-completeness warnings, not scanner failures.
  `claude-opus-5-5` is priced.

## Verification commands

```bash
~/.config/tokscale/autosubmit/tokscale --version
~/.config/tokscale/autosubmit/tokscale autosubmit status
systemctl --user list-timers --all --no-pager tokscale-autosubmit.timer
systemctl --user show tokscale-autosubmit.timer \
  -p ActiveState -p SubState -p NextElapseUSecMonotonic
crontab -l | sed -n '/BEGIN TOKSCALE AUTOSUBMIT/,/END TOKSCALE AUTOSUBMIT/p'
~/.config/tokscale/autosubmit/tokscale submit --dry-run
```

Expected when healthy: systemd shows a real next activation time (or cron shows the marked block),
and the last successful run in `autosubmit status` advances after each due tick.
