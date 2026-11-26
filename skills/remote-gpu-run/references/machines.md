# Known machines

Connect with each host's alias from `~/.ssh/config`. From outside the university network the
aliases go through a SOCKS5 proxy (`ProxyCommand nc -X 5 -x <proxy> %h %p`); a Windows-only
`ProxyCommand ssh.exe ...` line does not work on Linux. Checked on 2026-11-26.

## ANSR: GPU workstation

- 4x NVIDIA L40S 46 GB, shared with other users. Herdr profile `ansr`: `herdr --machine ansr ...`.
- `/data` is large but nearly full (95% used); home and `/tmp` are small. Check free space
  before writing large outputs and point caches and `TMPDIR` at `/data`.
- The HuggingFace CDN is blocked: download models locally and rsync them over.
- The user keeps their own Herdr workspaces there (for example `ansr_baseline`); leave them alone.

## m3: Monash M3 Slurm cluster

- Docs: <https://docs.erc.monash.edu/Compute/HPC/M3/>
- Accounts: `ar85`, `gp47`, `me12`.
- GPU partitions: `gpu` (A100, A40, T4; for example `--gres=gpu:A40:1`), `m3h` with `--qos=m3h`
  (H100), `m3g` (V100). Most other partitions are restricted; `short` is CPU only, 30 minutes.
- Login nodes are for light single-core work. Move data through the data transfer node. No
  scripts that poll the queue more often than once a minute. Jobs that leave GPUs idle are
  cancelled.
- Storage: home 15 GB; `/projects/<account>` 500 GB, for inputs, scripts and final results;
  `/scratch2/<account>` for working data, not backed up.

## fitcluster01: FIT GPU cluster (Slurm)

- Policies: <https://gigantic-garlic-b09.notion.site/FIT-Cluster-Policies-25d2e1de2ef7808caf58e361b5e53a97>
  (the user guide is linked from there).
- Account `fituser`. Partitions: `defq` (default; RTX 6000, RTX 8000, A40; no wall-time limit)
  and `A100` (needs `--qos=gpua100`; at most 4 A100s per user; at most 7 days).
- Slurm commands need a login shell (`bash -lc`). `.bashrc` prints `module: command not found`
  in a plain shell; ignore it.
- No AI agent tools or remote editors on login nodes. A local agent sending commands over SSH
  is allowed. Login nodes allow 2 CPU cores and 2 GB of memory per user.
- A100 jobs running over 1 hour with average GPU use under 60% are cancelled.
- One interactive session per user: at most 2 GPUs, at most 1 day, none on `A100`.
- `/home` is 50 GB per user. Large files go in `/nfsdata/data/` or `/data/others`. Files there
  are purged 360 days after their last read (persistent storage) or 90 days after creation
  (temporary storage).
- Pending jobs are ordered by fair share. Give large arrays a concurrency limit
  (`--array=1-200%10`). Do not request more memory than needed; it can crash a node.
