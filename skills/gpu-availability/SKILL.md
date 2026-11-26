---
name: gpu-availability
description: Find which GPUs are really free across shared GPU workstations, using a small usage recorder that the skill deploys on each machine (cron, once a minute, 14 days of history). Use when choosing a workstation or GPUs for a job, or when asked which machines or GPUs are free, idle or in use, and by whom.
---

# GPU availability

`nvidia-smi` shows one moment; a GPU that happens to be idle now may be in use again in five
minutes. This skill keeps a per-minute record on every workstation it checks and judges a GPU
by its recent history.

## Check

```
<skill-dir>/scripts/gpu-availability.sh [--hours N] [<ssh-host>...]
```

- Hosts default to the SSH targets of `herdr machine list`; pass SSH aliases to check others.
- `--hours` (default 6) is how long a GPU must have been idle to be listed as free.
- Hosts are checked in parallel; one that does not answer within about 40 s is reported as
  unreachable.

Each host gets a summary line, then one line per GPU from the highest index down:

```
<host> (4x <model>): idle GPUs [3,2]; history covers 25 min of 6 h; free right now [3,2,1]
  gpu 3  idle for all 25 min recorded; now 0% <used>/<total> MiB
  gpu 0  busy 40% of 25 min, last 3 min ago by <user>; now 71% <used>/<total> MiB (<user>)
```

- `idle GPUs` lists GPUs with no busy minute in the window that are also free now. A minute is
  busy when the GPU had a compute process, more than 1 GiB of memory in use or more than 10%
  utilization.
- While the history is shorter than the window, the line says how much it covers and adds the
  GPUs that are free right now. Treat those as a guess until the history is long enough.
- `recorder stopped ... ago` means the recorder has not written for over 3 minutes (cron
  disabled, machine rebooted without cron, disk full); look before trusting the history.

Pick from the idle GPUs, highest index first, unless the user or project names GPUs.

## The recorder

- On a host with `nvidia-smi` but no recorder, or an older copy, the check installs
  `scripts/gpu-usage-log.sh` as `~/.local/share/gpu-usage/gpu-usage-log.sh` and adds one cron
  entry that runs it every minute. No root and no long-running process; it resumes after a
  reboot. It also notes the cron entry in the machine's `~/AGENTS.md`.
- Each run reads every GPU 6 times, 10 s apart, and appends one line per GPU with the highest
  utilization and memory seen and the users of its compute processes, to
  `~/.cache/gpu-usage/<date>.tsv`.
- Day files older than 14 days are deleted on every run, so a 4-GPU machine keeps about 3 MB.
- Remove it: `ssh <host> 'bash ~/.local/share/gpu-usage/gpu-usage-log.sh uninstall'` (the
  records stay until you delete `~/.cache/gpu-usage`).

Slurm clusters are out of scope: their scheduler already knows what is free (`sinfo`; see the
remote-gpu-run skill).
