---
name: detached-gpu-queue
description: Plan, execute and monitor several long-running GPU tasks (training, evaluation sweeps, ablations, served-model swaps) unattended in /goal mode, through to delivered results. Use when the work outlives one turn or session, or needs tasks run in sequence across GPUs. Runs the plan as a detached, resumable queue script and arms a 1-minute watchdog as a background task, so a crash, GPU fault, stall, task failure or OOM risk wakes the session within minutes.
---

# Detached GPU Queue

Three mechanisms, three jobs:

| | Role | How |
|---|---|---|
| `/goal` | keeps the session from stopping before the goal is met | the goal check defers while background work runs |
| Queue script | runs the whole plan in order, for hours or days | detached: `setsid nohup`, parent is init |
| Watchdog | wakes the session when something needs attention | agent background task (e.g. Claude Code Bash `run_in_background: true`) that exits on any event |

The queue must outlive the session (a closed terminal or a context reset must not cost days of GPU work). The watchdog must belong to the session, because only a background task of the session notifies the model when it exits. Bundled files:

- `scripts/watch_queue.sh`: the watchdog.
- `assets/queue_template.sh`: a queue skeleton (task wrapper with skip-if-done, time limit and result line).

## 1. Plan

Turn the goal into an ordered task list before touching a GPU:

1. **Inventory.** List every run the goal needs (model × dataset × setting). Mark which already exist (reuse them, do not rerun) and which are prerequisites of others.
2. **Measure, then estimate.** Time a short pilot of each task type (a few hundred items, a few hundred steps) and record peak GPU memory and host RAM. Estimate wall time per task and the total; report it. Where a reference result exists (an earlier run, a different setting of the same job), compare the pilot with it; behaviour that does not match is a finding to resolve before the full run.
3. **Place.** Assign tasks to GPUs by memory. Put tasks that share a served model or a large load next to each other to minimise swaps. Use separate queues (lanes) only for tasks with disjoint GPUs and no shared services. On a shared machine, first establish which GPUs you may use and plan only on those; waiting for a GPU someone else holds is a queue step (with a heartbeat, below), never a reason to touch their processes.
4. **Order by value.** Results needed first, or that unblock decisions, go first. Group into phases; each phase ends with a DONE marker so it can be delivered on its own.
5. **Bound every task.** Give each task a wall-time limit (about 2× the estimate) and, where one input can explode (search, solver, generation), a per-item timeout that records a failure instead of hanging or exhausting memory.

## 2. Write the queue

Start from `assets/queue_template.sh`. Requirements:

- **Resumable and idempotent.** A finished task is skipped (done marker); a partial task resumes from its outputs (checkpoints, appended result rows). A crash is then fixed by relaunching, not by recomputing. If the project already has a task ledger or its own resume logic, use that to decide what is done; the template's `run_task` is only a default.
- **Self-provisioning.** Start the services a phase needs, wait until they answer, swap them between phases, and restore the original services at the end. Record each service's full command line.
- **Observable.** One log line per task: name, exit code, key metric, timestamp. Read progress and numbers from this log rather than recomputing them.
- **Loud failures.** A task that cannot make progress must exit non-zero or print a fixed marker (e.g. `GAVE UP`), never retry forever. The watchdog turns the marker into a wake-up. Do not trust exit codes alone: a tool can exit 0 with nothing done, so check the outputs and print the marker yourself. In a long task, print the marker for each failed sub-task when it happens, not only at the end.
- **Waits log a heartbeat.** A step that waits (for a GPU, a server, an earlier queue) writes a line such as `waiting for <what>` to the queue log every few minutes, so a long wait is not reported as a stall.
- **Decide what a failed task does.** Default: log it and continue with independent tasks; stop the queue only if later tasks depend on it.

Launch and record the PID:

```bash
setsid nohup bash queue_<name>.sh > "$RUN_ROOT/queue_<name>.log" 2>&1 &
ps -eo pid,args | grep -E "^ *[0-9]+ bash queue_<name>"
```

Anchor the pattern at the start of the command line, as the watchdog does: an unanchored pattern also matches the shell that wraps your own command, whose command line contains the same string.

**Never edit a running queue script.** Bash reads scripts incrementally, so an edit corrupts the running queue. To change the plan, write a successor (`queue_<name>_b.sh`) that skips finished tasks, then stop the old one by killing only its bash parent. Keep service children the successor will reuse.

## 3. Arm the watchdog

```bash
FAIL_GLOB='queue_<name>.log' FAIL_REGEX='GAVE UP' bash <skill dir>/scripts/watch_queue.sh "^bash queue_<name>" "$RUN_ROOT/DONE" "$RUN_ROOT"
```

Run it as a background task of the session. It checks every `INTERVAL` (60 s) and exits:

| Exit | Event |
|---|---|
| 0 | DONE file exists |
| 1 | queue process gone without DONE (crash, kill) |
| 2 | `nvidia-smi` fails or times out, a GPU disappears, or a GPU reports `ERR!` / "requires reset" |
| 3 | no file under the watched paths changed for `STALL_MIN` (45) min |
| 4 | a `FAIL_GLOB` file (default `*.log`) written after the watchdog started matches `FAIL_REGEX` |
| 5 | available RAM below `MIN_AVAIL_GB` (8) |

Settings:
- Watch every path the queue writes to; otherwise a long phase writing elsewhere looks like a stall.
- Set `STALL_MIN` above the longest legitimate silent step (model load, service swap, a slow checkpoint).
- Pick a `FAIL_REGEX` that matches only fatal markers, and narrow `FAIL_GLOB` to logs the queue itself writes. Third-party logs (model servers, frameworks) contain handled tracebacks and retried warnings that would wake the session for nothing.
- Exit 3 means only that nothing changed; a wait without a heartbeat looks the same as a hang, so check which one it is before acting.

The watchdog only reads state. Arm one for every queue; a waiter that only watches for DONE can hide a hang for many hours.

## 4. Run the goal loop

```
plan -> pilot -> launch queue -> arm watchdog -> end the turn
                                     |
                         watchdog exits (session wakes)
       +-----------------------------+------------------------------+
   exit 0: deliver                                          exit 1-5: recover
   summarise results, save reports,                         diagnose, fix, relaunch
   commit, post updates, next goal step                     (successor), re-arm watchdog
```

- **Do not poll while it runs.** At a goal check-in, a running watchdog means the queue is healthy by construction: say so in one line and keep waiting. Read logs, outputs and GPU state only when the user asks for status, and then report finished results, the current task, and the ETA.
- **Deliver per phase.** When a phase DONE marker exists, summarise and save that phase without waiting for the whole queue.
- **Diagnose a non-zero exit before changing anything:**
  - The watchdog report (exit code, GPU table, free memory) and the queue log tail.
  - The failing task's log.
  - Process state: `ps -eo pid,stat,etime,rss,args`. A process in state `D` with a driver wait channel (`cat /proc/<pid>/wchan`) is stuck in the GPU driver and cannot be killed; report it to the user rather than acting.
  - Kernel messages for GPU errors and OOM kills: `dmesg` or `journalctl -k`, which may need privileges the user must grant.
- **Recover.** Fix the cause, not the symptom: add a per-item timeout, lower the batch size or concurrency, or skip a reproducibly failing item and record it. Test the fix on the failing input, launch a successor queue, and re-arm the watchdog. Log the incident and the fix with the results.
- **Stay within authority.** Actions that affect the machine or other users (system configuration, killing others' processes, freeing GPUs used by others) need the user's explicit consent.

## On a remote server

The same queue and watchdog work on a GPU workstation reached over SSH; only where each runs
changes.

- **Queue: in the server's Herdr, not a foreground SSH command.** Start it in a workspace of its
  own (`herdr --machine <label> pane run <pane> "cd <dir> && RUN_ROOT=<dir> bash queue_<name>.sh 2>&1 | tee -a <dir>/queue_<name>.log"`;
  the remote-gpu-run skill covers setting up `herdr --machine`). A dropped connection then
  costs nothing, and the user can watch the queue in Herdr.
- **Watchdog: unchanged, run on the server, owned by the local session.** Send the script over
  SSH as a background task:

  ```bash
  ssh -o ServerAliveInterval=30 <host> "STALL_MIN=45 FAIL_GLOB='queue_*.log' FAIL_REGEX='GAVE UP' bash -s -- '^bash queue_<name>' <remote DONE file> <remote paths>" < <skill dir>/scripts/watch_queue.sh
  ```

  Exits 0-5 mean the same as locally. Exit 255 means the SSH connection dropped, not that the
  queue failed: reconnect, glance at the queue log, and arm the watchdog again.
- Send short commands (status, `git pull`, reading logs) over one multiplexed SSH connection
  instead of a new login each time.
- A `pkill -f` or `pgrep -f` pattern sent over SSH also matches the remote shell running it;
  anchor it and send it in its own SSH call.
- Do not rsync over a file the queue is still appending to: the queue keeps writing to the old
  file. Copy results out under new names.
- Provision everything before launching (models, data, packages, files the scoring step needs),
  and run the whole pipeline, scoring included, in the pilot on the new machine: a missing
  resource otherwise fails the last step after all the GPU work.

## Limits

- The session is the only notification channel. If it ends, the queue keeps running but nothing reacts. On resume, re-arm the watchdog first, then read the queue log.
- The watchdog detects; it does not heal. Self-recovery (killing a stalled task, skipping after repeated failures, memory caps) belongs in the queue and task wrappers.
