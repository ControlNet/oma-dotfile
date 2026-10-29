# Tokscale OMO session path support (2026-10-09, updated 2026-10-12)

## Upstream status

- [PR #1409](https://github.com/junhoyeo/tokscale/pull/1409) merged on 2026-10-11, merge commit
  `8ba2e9d7128e67424f7aeb07aabefd4ac5ed1c16`; [issue #1375](https://github.com/junhoyeo/tokscale/issues/1375)
  closed right after. An earlier attempt, [PR #1380](https://github.com/junhoyeo/tokscale/pull/1380),
  was closed without merging on 2026-10-04.
- Main at `bd62b8c4e07269e5314fac06c6d23262dc714633` scans `~/.omo/agent/sessions` by default,
  honors `OMO_CODING_AGENT_DIR` and `OMO_CODING_AGENT_SESSION_DIR`, and discovers task children from
  extra Senpi scan paths. OMO usage still belongs to client `senpi`. Checked by source inspection of
  [scanner.rs](https://github.com/junhoyeo/tokscale/blob/bd62b8c4e07269e5314fac06c6d23262dc714633/crates/tokscale-core/src/scanner.rs#L801),
  not a local build of main.
- As of 2026-10-12 the latest release and npm `latest` are still
  [v4.18.0](https://github.com/junhoyeo/tokscale/releases/tag/v4.18.0) (2026-10-05), which predates
  the fix, so `bunx tokscale@latest` does not include it yet.

## Behavior of 4.18.0

v4.18.0 resolves the `senpi` client to `$SENPI_CODING_AGENT_DIR/sessions`, falling back to
`~/.senpi/agent`. It does not scan `~/.omo/agent/sessions` or read `OMO_CODING_AGENT_DIR`. Sources:
[client registry](https://github.com/junhoyeo/tokscale/blob/v4.18.0/crates/tokscale-core/src/clients.rs#L827),
[scanner](https://github.com/junhoyeo/tokscale/blob/v4.18.0/crates/tokscale-core/src/scanner.rs#L801).

Tested with `models --json --no-spinner -c senpi`, clearing the OMO/Senpi path variables between runs:

| Path selection | OMO Native sessions found |
| --- | --- |
| Default | none |
| `SENPI_CODING_AGENT_DIR="$HOME/.omo/agent"` | all, including task children |
| `OMO_CODING_AGENT_DIR="$HOME/.omo/agent"` alone | none |
| `TOKSCALE_EXTRA_DIRS="senpi:$HOME/.omo/agent/sessions"` | main sessions only; task children missed |

So on 4.18.0 the workaround is `SENPI_CODING_AGENT_DIR` pointing at the agent directory (not its
`sessions` child).

## Reproduce the working override

```bash
~/.config/tokscale/autosubmit/tokscale --version
SENPI_CODING_AGENT_DIR="$HOME/.omo/agent" \
  ~/.config/tokscale/autosubmit/tokscale models --json --no-spinner -c senpi
```

Expected on 4.18.0: `totalMessages` is non-zero only with the override. The override must also be in
the environment of scheduled autosubmit, or OMO usage is never submitted. A release that contains
PR #1409 makes the override unnecessary.
