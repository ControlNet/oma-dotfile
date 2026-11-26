---
name: remote-gpu-run
description: Run long GPU experiments on remote machines over SSH and watch them until they finish - GPU workstations through their Herdr server (`herdr --machine`), Slurm clusters through sbatch with a watcher on the local machine. Use when asked to run, launch, queue, monitor or fetch the results of training, evaluation or other long jobs on a remote server, GPU workstation or HPC cluster.
---

# Remote GPU run

For two kinds of machine: a GPU workstation reached over SSH, and a Slurm cluster with GPU
nodes. The agent stays on the local machine and sends commands; long work runs on the remote
side. Facts about a machine live in `~/AGENTS.md` on that machine; facts about a project on it
(data paths, allowed GPUs, environment fixes) live in the project's AGENTS.md or
`.omo/knowledges/`.

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
  Inside such a script, give every `ssh` and `srun` `< /dev/null`; otherwise they read the rest
  of the script as their input and the commands after them never run.
- A `pkill -f` or `pgrep -f` pattern sent over ssh also matches the remote shell running it,
  which kills the ssh session. Send it in its own ssh call with an anchored pattern, e.g.
  `pgrep -u $USER -f '^python train.py'`.

## Before the first run on a machine

- Read the machine's notes: `ssh <host> cat ~/AGENTS.md`, and follow them. If there is none,
  write one from the machine's documentation and usage policy and what you find (workstation or
  cluster, GPUs, accounts, partitions and QoS, storage, limits, links to the docs). Add lasting
  facts you learn later; keep project details out of it.
- Common rules: nothing heavy on login nodes, no agent tools on login nodes, no queue polling
  more often than once a minute, jobs that hold GPUs idle get cancelled.
- Check free GPUs (`nvidia-smi`) and never touch other users' processes, jobs, Herdr
  workspaces or tmux sessions. On a workstation, use the GPUs the user or project names; if
  none are named, take free ones from the highest index down (3, 2, 1, 0) and pin them with
  `CUDA_VISIBLE_DEVICES`.

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
- Keep the log current, or the stall check reports a healthy job as stuck: unbuffered output
  (`python -u` or `PYTHONUNBUFFERED=1`) and a progress line at least every few minutes.

## GPU workstation: its Herdr server

1. `herdr machine list --json`. If the host has no profile:
   - If `ssh <host> 'command -v herdr || ls ~/.local/bin/herdr'` finds nothing, install it there:
     `ssh <host> 'curl -fsSL https://herdr.dev/install.sh | sh'`. Local and remote Herdr must be
     compatible versions (`herdr --version` on both).
   - Add the profile and tell the user: `herdr machine add <ssh-alias> --label <label>`.
2. One workspace per run, never inside the user's own workspaces:
   `herdr --machine <label> workspace create --label <run> --cwd <remote-dir> --no-focus`, and
   read the pane from `.result.root_pane.pane_id`.
3. Start the job with a log on the data disk and an exit marker that also lands in the log
   (this form works in bash and zsh):
   `herdr --machine <label> pane run <pane> "( <command>; echo RUN_EXIT=\$? ) 2>&1 | tee -a <log>"`
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

## Debugging on a Slurm cluster

For trying things on a GPU node before a long batch run:

1. Pick a partition you may use that has idle nodes: compare `sinfo -o '%P %F %G'` (nodes
   allocated/idle/other/total, GPUs) with your QoS from
   `sacctmgr -n -P show assoc user=$USER format=Account,QOS` and each partition's `AllowQos` in
   `scontrol show partition`. A CPU-only partition is enough when no GPU is needed.
2. Hold an allocation with a placeholder job, so nothing waits on the login node while it is
   pending:
   `sbatch --parsable -J debug -t 01:00:00 --gres=gpu:1 <account, partition, cpus, mem> -o /dev/null --wrap 'sleep infinity'`
3. Wait for it locally: `<skill-dir>/scripts/remote-watch.sh <host> --job <id> --until-running`
   returns once it runs and prints its node.
4. Run each command inside it:
   `ssh <host> "srun --jobid=<id> --overlap -n1 bash -lc 'cd <repo> && <command>'" < /dev/null`.
   Slurm older than 20.11 has no `--overlap` and does not need it. For an interactive program,
   open `ssh -t <host> srun --jobid=<id> --overlap --pty bash` in a local Herdr pane and drive
   that pane; some clusters also let you `ssh` from the login node into the allocated node.
5. `scancel <id>` as soon as you are done. A debug allocation leaves the GPU idle most of the
   time and may count as an interactive session, so keep `--time` short, prefer a small GPU or
   CPU only, and avoid partitions that cancel jobs for low GPU use.

## Watching

`remote-watch.sh` exits 0 when the job is finished (it left the queue or `--done` matched the
log) or, with `--until-running`, has started; 1 when the log has not changed for `--stall-min`
minutes while the job runs; 2 when the host stops answering. On every exit read the log tail
and decide; for a stall also check that the process is alive and the GPU busy (`nvidia-smi`, or
`sstat`/`jobstats` on a cluster). Start the watcher again if the run continues.

When the run ends, rsync the results back and check them (row counts, error or fallback rate)
before reporting.

## Report

Where it ran (host and GPUs, or job ID), the commit, log and result paths, the final state, and
anything stuck or waiting on the user.
