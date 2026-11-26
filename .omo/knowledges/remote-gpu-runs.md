# Remote GPU runs: what was tried

Tried on 2026-11-26 for the `remote-gpu-run` skill, on a shared GPU workstation and two Slurm
clusters. Each machine's own notes are in `~/AGENTS.md` on that machine.

- **One ssh per command** costs 0.3 to 0.4 s and prints the login banner every time. With
  `ControlMaster=auto` and `ControlPersist`, the first connection takes about 0.8 s and later
  commands about 0.05 s. The control socket path must stay under about 100 characters: a socket
  inside a long scratch directory silently failed to come up.
- **`herdr machine add <alias>`** lets the local Herdr drive the remote Herdr server:
  `herdr --machine <label> pane run`, then `pane wait-output --regex` blocks locally until the
  remote job prints its marker (a 40 s job blocked for 41 s, no polling). Herdr keeps its own
  multiplexed ssh connection. The remote panes also show up in the local Herdr window.
- **Slurm**: `sbatch --wait` and watch loops would sit on the login node, which the clusters
  limit (one forbids agent tools there, another forbids queue polling under one minute). The
  watcher therefore runs locally and checks `sacct` over the shared connection. On one cluster
  Slurm commands only work in a login shell (`bash -lc`).
- **Pitfalls hit**: a `pkill -f` pattern sent over ssh matched the ssh session's own command
  line and killed it, so the rest of that command never ran. A `~/...` path quoted with
  `printf %q` is not expanded on the remote, so the watcher has to expand it there. In a script
  piped through `ssh <host> bash -l -s`, an inner `ssh` or `srun` read the rest of the script
  from stdin, so the `scancel` after it never ran; they need `< /dev/null`.
- **Debug allocations**: `salloc --no-shell` returns once granted but waits on the login node
  while pending, so the skill holds the allocation with `sbatch --wrap 'sleep infinity'` and
  waits locally with `remote-watch.sh --until-running` (a CPU-only test started in 14 s).
  `srun --jobid=<id>` then runs each command on the node at once; Slurm 20.11 and later need
  `--overlap` for that, older versions reject the flag.
- The earlier logic-llm runs used one ssh master plus the remote `herdr` CLI over ssh, and 38
  local polling loops; two hangs went unnoticed because the loops only looked for completion,
  hence the stall check in `remote-watch.sh`.
- **SSH timeouts**: `ConnectTimeout` does not cover a `ProxyCommand`. Through a SOCKS proxy, ssh
  to a machine that is down hung for minutes, so both skills' scripts wrap every ssh call in
  `timeout`.
- **GPU availability**: a per-minute cron recorder (6 readings 10 s apart, per-minute maximum)
  was chosen over a long-running daemon: it resumes after reboots and needs no root, and
  `systemd --user` without linger does not start after a reboot. Two here-documents on one
  command both feed stdin, so the later one silently replaced the data meant for the first.
