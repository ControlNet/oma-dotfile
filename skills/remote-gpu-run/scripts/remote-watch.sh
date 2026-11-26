#!/usr/bin/env bash
# Watch remote jobs from the local machine and exit when they need attention.
#
# usage: remote-watch.sh <ssh-host> [--job <id>[,<id>...]]... [--log <remote-path>]
#                        [--done <regex>] [--stall-min <minutes>] [--interval <seconds>]
#                        [--until-running]
#
# --job: Slurm job IDs, repeated or comma-separated. A job array's ID covers all its tasks. All
#   jobs are checked with one sacct call per interval.
# --log: quote a ~/ path ('~/run.log') so the local shell leaves it for the remote one.
# --until-running: return as soon as a job starts (prints its node), e.g. for a debug allocation.
# Exit codes: 0 finished (every job COMPLETED, or --done matched the log), or started with
#               --until-running;
#             1 stalled (the log has not changed for --stall-min minutes while a job runs,
#               counted from no earlier than the watcher's start);
#             2 the host stopped answering;
#             3 a job ended in another state (FAILED, TIMEOUT, OUT_OF_MEMORY, NODE_FAIL,
#               CANCELLED, ...), or with --until-running ended before it ran;
#             64 usage error.
# Every check reuses one shared SSH connection (ControlMaster), so it does not log in again.
set -u

usage() { sed -n '4,6p' "$0" >&2; exit 64; }
[ $# -ge 1 ] || usage
host=$1; shift
job="" log="" done_re="" stall_min=0 interval=300 until_running=0
while [ $# -gt 0 ]; do
  case $1 in
    --job) job=${job:+$job,}${2:?}; shift 2 ;;
    --log) log=${2:?}; shift 2 ;;
    --done) done_re=${2:?}; shift 2 ;;
    --stall-min) stall_min=${2:?}; shift 2 ;;
    --interval) interval=${2:?}; shift 2 ;;
    --until-running) until_running=1; shift ;;
    *) usage ;;
  esac
done
[ -n "$job$log" ] || usage
[ "$until_running" = 0 ] || [ -n "$job" ] || usage

ssh_opts=(-q -T -o BatchMode=yes -o ConnectTimeout=20 -o ControlMaster=auto -o "ControlPath=$HOME/.ssh/cm-%C"
          -o ControlPersist=30m -o ServerAliveInterval=30 -o ServerAliveCountMax=4)

# Runs in a remote login shell, so Slurm's environment is loaded; prints key=value lines, one
# "job=<id>|<state>|<exit code>|<elapsed>|<nodes>" line per job or array task.
remote_script=$(cat <<EOF
job=$(printf %q "$job") log=$(printf %q "$log") done_re=$(printf %q "$done_re")
case \$log in "~/"*) log="\$HOME/\${log#"~/"}" ;; esac
if [ -n "\$job" ]; then
  sacct -j "\$job" -X -n -P --format=JobID,State,ExitCode,Elapsed,NodeList 2>/dev/null | sed 's/^/job=/'
fi
if [ -n "\$log" ] && [ -f "\$log" ]; then
  echo "age=\$(( \$(date +%s) - \$(stat -c %Y "\$log") ))"
  [ -n "\$done_re" ] && echo "done=\$(tail -n 200 "\$log" | grep -E -m1 -- "\$done_re")"
fi
echo "ok=1"
EOF
)

field() { printf '%s\n' "$reply" | sed -n "s/^$1=//p" | head -1; }
log_tail() {
  [ -n "$log" ] || return 0
  timeout 60 ssh "${ssh_opts[@]}" "$host" bash -s <<<"log=$(printf %q "$log"); case \$log in \"~/\"*) log=\"\$HOME/\${log#\"~/\"}\" ;; esac; tail -n 5 \"\$log\"" 2>/dev/null
}

start=$(date +%s)
failures=0
while :; do
  # timeout: ConnectTimeout does not cover a ProxyCommand to a host that is down.
  reply=$(timeout 120 ssh "${ssh_opts[@]}" "$host" bash -l -s <<<"$remote_script" 2>/dev/null)
  if [ "$(field ok)" != 1 ]; then
    failures=$((failures + 1))
    if [ "$failures" -ge 10 ]; then
      echo "$host: no answer after $failures tries"; exit 2
    fi
    sleep "$interval"; continue
  fi
  failures=0
  age=$(field age) matched=$(field done)
  jobs=$(printf '%s\n' "$reply" | sed -n 's/^job=//p')

  if [ -n "$matched" ]; then
    echo "$host: finished: $matched"; log_tail; exit 0
  fi

  running="" active=0 failed=0
  if [ -n "$jobs" ]; then
    while IFS='|' read -r id state _ _ nodes; do
      case ${state%% *} in  # "CANCELLED by <uid>"
        PENDING|RUNNING|REQUEUED|RESIZING|SUSPENDED|CONFIGURING|COMPLETING|STAGE_OUT|SIGNALING) active=1 ;;
        COMPLETED) ;;
        *) failed=1 ;;
      esac
      [ "${state%% *}" = RUNNING ] && running="${running:+$running, }$id on $nodes"
    done <<<"$jobs"
    summary=$(awk -F'|' '{ print "  " $1, $2, "exit " $3, $4, $5 }' <<<"$jobs")
    if [ "$until_running" = 1 ]; then
      [ -n "$running" ] && { echo "$host: running: $running"; exit 0; }
      [ "$active" = 0 ] && { echo "$host: ended before it ran:"; echo "$summary"; exit 3; }
    elif [ "$failed" = 1 ]; then
      echo "$host: a job ended without completing:"; echo "$summary"; log_tail; exit 3
    elif [ "$active" = 0 ]; then
      echo "$host: all jobs completed:"; echo "$summary"; log_tail; exit 0
    fi
  fi

  # A log that was already old when the watcher started is not a stall yet.
  since_start=$(( $(date +%s) - start ))
  [ -n "$age" ] && [ "$age" -gt "$since_start" ] && age=$since_start
  if [ "$stall_min" -gt 0 ] && [ -n "$age" ] && [ "$age" -gt $((stall_min * 60)) ] \
      && { [ -z "$job" ] || [ -n "$running" ]; }; then
    echo "$host: stalled: $log unchanged for $((age / 60)) min${running:+ (running: $running)}"
    log_tail; exit 1
  fi
  sleep "$interval"
done
