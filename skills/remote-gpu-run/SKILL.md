---
name: remote-gpu-run
description: Run long GPU experiments on remote machines over SSH and watch them until they finish - GPU workstations through their Herdr server (`herdr --machine`), Slurm clusters through sbatch with a watcher on the local machine. Use when asked to run, launch, queue, monitor or fetch the results of training, evaluation or other long jobs on a remote server, GPU workstation or HPC cluster.
---

# Remote GPU run

For two kinds of machine: a GPU workstation reached over SSH, and a Slurm cluster with GPU
nodes. The agent stays on the local machine and sends commands; long work runs on the remote
side. Facts about a particular machine (SSH alias, role, data paths, allowed GPUs, Slurm account,
partition and QoS, environment fixes, usage policy) belong in the project's AGENTS.md or
`.omo/knowledges/`. Read them first and add what you learn.

## Connect

- Use the host's alias from `~/.ssh/config` with `BatchMode=yes`. If login fails, report it and
  stop; keys and accounts are the user's to fix.
- Send short commands (checks, `git pull`, `sacct`, `nvidia-smi`) over one shared connection per
  host, so each command reuses the open login instead of logging in again:
  `ssh -q -T -o BatchMode=yes -o ControlMaster=auto -o ControlPath=~/.ssh/cm-%C -o ControlPersist=30m -o ServerAliveInterval=30 <host> '<command>'`
  The socket path must stay under about 100 characters. `ssh -O check <host>` (same options)
  shows whether the master is up; if it dropped, say so and open it again.
- Slurm and module commands usually need a login shell: `bash -lc '...'`. For anything longer
  than one line, pipe a script instead of nesting quotes: `ssh <host> bash -l -s < script.sh`.
- A `pkill -f` or `pgrep -f` pattern sent over ssh also matches the remote shell running it,
  which kills the ssh session. Send it in its own ssh call with an anchored pattern, e.g.
  `pgrep -u $USER -f '^python train.py'`.

## Before the first run on a machine

- Read the cluster's or machine's usage policy. Common rules: nothing heavy on login nodes, no
  agent tools on login nodes, no queue polling more often than once a minute, jobs that hold
  GPUs idle get cancelled.
- Check free GPUs (`nvidia-smi`), use only the GPUs the project allows, and never touch other
  users' processes, jobs, Herdr workspaces or tmux sessions.

## Code, data and environment

- Code: commit and push locally, then `git pull --ff-only` on the remote. Do not edit code there.
- Data and results: `rsync -a --partial -e "ssh -o ControlPath=~/.ssh/cm-%C" ...`, through the
  cluster's data transfer node if it has one. Never rsync over a file a running job still
  writes.
- Build the environment with the project's tool (pixi, uv or conda) on the remote. Put caches
  and `TMPDIR` on the data or scratch disk when home or `/tmp` is small. If the remote cannot
  reach a model or dataset host, download locally and rsync.
- Check the first outputs, not only the exit code: a broken kernel or a missing file can fall
  back silently and still exit 0. On a workstation, run a few steps first. On a busy cluster,
  do not spend an allocation on a pilot: try a few steps locally or on a workstation, make the
  job check its own first results (error or fallback rate) and exit early when they are wrong,
  and look at the first outputs as soon as they appear.
- Make long runs resumable (skip finished items, write results per item), so a crash or a
  preemption costs one item.

## GPU workstation: its Herdr server

1. `herdr machine list --json`. If the host has no profile, ask the user to add one:
   `herdr machine add <ssh-alias> --label <label>`. It may install or start Herdr on the remote
   and ask them to confirm.
2. One workspace per run, never inside the user's own workspaces:
   `herdr --machine <label> workspace create --label <run> --cwd <remote-dir> --no-focus`, and
   read the pane from `.result.root_pane.pane_id`.
3. Start the job with a log on the data disk and an exit marker:
   `herdr --machine <label> pane run <pane> "<command> 2>&1 | tee -a <log>; echo RUN_EXIT=\${PIPESTATUS[0]}"`
4. Wait in background jobs: `herdr --machine <label> pane wait-output <pane> --regex 'RUN_EXIT=[0-9]+'`
   (no `--timeout` waits until it appears), and for hangs
   `<skill-dir>/scripts/remote-watch.sh <host> --log <log> --done 'RUN_EXIT=' --stall-min 30`.
5. To stop: `herdr --machine <label> pane send-keys <pane> ctrl+c`.
6. Close the run's workspace once its results are back.

## Slurm cluster

1. Put the sbatch script in the repository: account, partition, QoS, `--time`, GPUs, memory, and
   `--output` on the project or scratch disk. Size `--time` realistically; it helps backfill.
2. Submit with `sbatch --parsable` and note the job ID.
3. Wait from the local machine, never on the login node (no `sbatch --wait`, loops or tmux
   there): run `<skill-dir>/scripts/remote-watch.sh <host> --job <id> --log <slurm-output> --stall-min 30`
   as a background job. It checks `sacct` every `--interval` seconds (default 300; keep it at 60
   or more on clusters).
4. A job pending for long: report the reason from `squeue -j <id> -o %r`. Moving it to another
   partition, account or QoS is the user's decision.
5. `scancel` only your own jobs.

## Watching

`remote-watch.sh` exits 0 when the job is finished (it left the queue or `--done` matched the
log), 1 when the log has not changed for `--stall-min` minutes while the job runs, and 2 when the
host stops answering. On every exit read the log tail and decide; for a stall also check that
the process is alive and the GPU busy (`nvidia-smi`, or `sstat`/`jobstats` on a cluster). Start
the watcher again if the run continues.

When the run ends, rsync the results back and check them (row counts, error or fallback rate)
before reporting.

## Report

Where it ran (host and GPUs, or job ID), the commit, log and result paths, the final state, and
anything stuck or waiting on the user.
