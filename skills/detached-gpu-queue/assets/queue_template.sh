#!/usr/bin/env bash
# Queue template: one detached, resumable script that runs a whole plan of long GPU tasks in order.
# Copy it, fill in the task functions and the PLAN section, then launch it detached:
#   setsid nohup bash queue_<name>.sh > "$RUN_ROOT/queue_<name>.log" 2>&1 &
# Never edit this file while it runs (bash reads scripts incrementally); write a successor instead.
set -u
RUN_ROOT=${RUN_ROOT:?set RUN_ROOT to the directory for outputs, logs and DONE markers}
log() { echo "$* $(date -Is)"; }

# Wait until an HTTP endpoint answers (e.g. a model server's health route).
wait_http() {  # <url> <timeout s>
  local t=0; until curl -sf "$1" > /dev/null; do sleep 10; t=$((t + 10)); [ $t -ge "$2" ] && return 1; done
}

# Wait until a command succeeds (a free GPU, an earlier queue's DONE file, ...), logging a heartbeat every
# HEARTBEAT_S seconds so the watchdog does not report the wait as a stall.
wait_for() {  # <what> <command...>
  local what=$1; shift
  local t=0
  until "$@" > /dev/null 2>&1; do
    [ $((t % ${HEARTBEAT_S:-600})) -eq 0 ] && log "waiting for $what"
    sleep 30; t=$((t + 30))
  done
}
# e.g. wait_for "GPU 2 free" bash -c '[ "$(nvidia-smi -i 2 --query-compute-apps=pid --format=csv,noheader | wc -l)" = 0 ]'

# One task: skip if done, run with a hard time limit, record exit code and the result line.
# run_task writes the task's DONE marker only when the command exits 0. The command itself should resume from its
# partial outputs (checkpoints, appended rows) when restarted, and may write its metric to result.txt in its task dir.
run_task() {  # <name> <max hours> <command...>
  local name=$1 hours=$2; shift 2
  local dir="$RUN_ROOT/tasks/$name"; mkdir -p "$dir"
  [ -e "$dir/DONE" ] && { log "$name already done"; return 0; }
  log "$name start"
  timeout --signal=TERM --kill-after=120 "${hours}h" "$@" > "$dir/task.log" 2>&1; local rc=$?
  [ $rc -eq 0 ] && touch "$dir/DONE"
  log "$name exit $rc $(tail -1 "$dir/result.txt" 2>/dev/null)"
  return $rc
}

# --- PLAN: phases in priority order; each phase ends with its own DONE marker -------------------------------------
# Phase 1
# start_server_A                      # start shared services if down, wait_http until ready
# run_task p1_job1 6 python train.py --resume ...
# run_task p1_job2 6 python eval.py ...
# touch "$RUN_ROOT/phase1.DONE"; log "phase1 done"
#
# Phase 2
# stop_server_A; start_server_B       # swap per-phase services
# run_task p2_job1 12 ...
# touch "$RUN_ROOT/phase2.DONE"; log "phase2 done"
#
# restore_standing_services           # leave the machine as it was found
# touch "$RUN_ROOT/DONE"; log "queue done"
