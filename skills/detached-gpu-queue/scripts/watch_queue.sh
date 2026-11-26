#!/usr/bin/env bash
# Watchdog for a detached GPU queue. Run it as a background task of the agent session: it checks every INTERVAL seconds
# and exits as soon as something needs attention, so the session is woken at once instead of when the queue finishes.
#   exit 0  the DONE file exists (queue finished)
#   exit 1  no process matches the queue regex and the DONE file is missing (crashed or killed)
#   exit 2  GPU problem: nvidia-smi fails or times out, fewer GPUs than at start, or a GPU reports ERR! / "requires reset"
#   exit 3  stall: no file under the watched paths changed for STALL_MIN minutes
#   exit 4  text written to a file matching FAIL_GLOB under the watched paths after the watchdog started matches
#           FAIL_REGEX (a marker already there when it started does not count, so re-arming after a failure is safe)
#   exit 5  available RAM below MIN_AVAIL_GB (an OOM kill is close)
# Usage: watch_queue.sh <queue process regex, matched against `ps -eo args`> <DONE file> <watched path>...
# Env: INTERVAL=60  STALL_MIN=45  GPUS=<count at start>  MIN_AVAIL_GB=8
#      FAIL_GLOB='*.log'  FAIL_REGEX='' (empty disables exit 4)
set -u
[ $# -ge 3 ] || { sed -n '2,13p' "$0"; exit 64; }
QUEUE=$1; DONE=$2; shift 2
PATHS=("$@")
INTERVAL=${INTERVAL:-60}; STALL_MIN=${STALL_MIN:-45}; MIN_AVAIL_GB=${MIN_AVAIL_GB:-8}
FAIL_GLOB=${FAIL_GLOB:-*.log}; FAIL_REGEX=${FAIL_REGEX:-}
GPUS=${GPUS:-$(timeout 60 nvidia-smi -L 2>/dev/null | grep -c '^GPU ')}

report() {
  echo "[$(date -Is)] $1"
  timeout 60 nvidia-smi --query-gpu=index,memory.used,utilization.gpu,temperature.gpu --format=csv,noheader 2>&1
  free -g | sed -n 2p
}
START=$(mktemp); trap 'rm -f "$START"' EXIT
# Sizes of the fail-glob files at start: only text appended after them is searched. -H follows watched paths that are
# themselves symlinks (e.g. a run directory linked to a data disk).
declare -A seen
if [ -n "$FAIL_REGEX" ]; then
  while IFS= read -r -d '' f; do seen[$f]=$(stat -c %s "$f"); done \
    < <(find -H "${PATHS[@]}" -type f -name "$FAIL_GLOB" -print0 2>/dev/null)
fi

echo "watching '$QUEUE' until $DONE: every ${INTERVAL}s, stall ${STALL_MIN} min, ${GPUS} GPUs, RAM >= ${MIN_AVAIL_GB} GB, fail regex '${FAIL_REGEX}' $(date -Is)"
while :; do
  [ -e "$DONE" ] && { report "DONE: $DONE"; exit 0; }

  # Snapshot ps first: a grep in the same pipeline would match its own command line. Skip this watchdog's own line.
  procs=$(ps -eo args | grep -v -- "watch_queue.sh")
  if ! grep -qE -- "$QUEUE" <<< "$procs"; then
    sleep 5; [ -e "$DONE" ] && { report "DONE: $DONE"; exit 0; }
    report "CRASHED: no process matches '$QUEUE' and $DONE is missing"; exit 1
  fi

  smi=$(timeout 60 nvidia-smi 2>&1); rc=$?
  n=$(timeout 60 nvidia-smi -L 2>/dev/null | grep -c '^GPU ')
  if [ $rc -ne 0 ] || [ "$n" -lt "$GPUS" ] || grep -qE "ERR!|requires reset" <<< "$smi"; then
    report "GPU: nvidia-smi rc=$rc, $n of $GPUS GPUs"; grep -E "ERR!|requires reset" <<< "$smi"; exit 2
  fi

  # Idle time counts from the newest file or the watchdog start, whichever is later: a queue still waiting for its turn
  # (old or empty output dirs) is not a stall at arm time.
  newest=$( { find -H "${PATHS[@]}" -type f -printf '%T@\n' 2>/dev/null; stat -c %Y "$START"; } | sort -n | tail -1)
  if [ $(( $(date +%s) - ${newest%.*} )) -gt $((STALL_MIN * 60)) ]; then
    report "STALL: nothing under ${PATHS[*]} changed for more than ${STALL_MIN} min"; exit 3
  fi

  if [ -n "$FAIL_REGEX" ]; then
    hit=""
    while IFS= read -r -d '' f; do
      tail -c +$(( ${seen[$f]:-0} + 1 )) "$f" | grep -qE -- "$FAIL_REGEX" && hit+="$f"$'\n'
    done < <(find -H "${PATHS[@]}" -type f -name "$FAIL_GLOB" -newer "$START" -print0 2>/dev/null)
    [ -n "$hit" ] && { report "FAILED: '$FAIL_REGEX' in"; printf '%s' "$hit"; exit 4; }
  fi

  avail=$(awk '/^MemAvailable:/ {print int($2 / 1048576)}' /proc/meminfo)  # GB; free's labels are translated
  [ "$avail" -lt "$MIN_AVAIL_GB" ] && { report "LOW MEMORY: ${avail} GB available"; exit 5; }

  sleep "$INTERVAL"
done
