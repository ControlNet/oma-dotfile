#!/usr/bin/env bash
# Watch a remote job from the local machine and exit when it needs attention.
#
# usage: remote-watch.sh <ssh-host> [--job <slurm-job-id>] [--log <remote-path>]
#                        [--done <regex>] [--stall-min <minutes>] [--interval <seconds>]
#
# Exit codes: 0 finished (the Slurm job left the queue, or --done matched the log),
#             1 stalled (the log has not changed for --stall-min minutes while the job runs),
#             2 the host stopped answering, 64 usage error.
# Every check reuses one shared SSH connection (ControlMaster), so it does not log in again.
set -u

usage() { sed -n '4,5p' "$0" >&2; exit 64; }
[ $# -ge 1 ] || usage
host=$1; shift
job="" log="" done_re="" stall_min=0 interval=300
while [ $# -gt 0 ]; do
  case $1 in
    --job) job=${2:?}; shift 2 ;;
    --log) log=${2:?}; shift 2 ;;
    --done) done_re=${2:?}; shift 2 ;;
    --stall-min) stall_min=${2:?}; shift 2 ;;
    --interval) interval=${2:?}; shift 2 ;;
    *) usage ;;
  esac
done
[ -n "$job$log" ] || usage

ssh_opts=(-q -T -o BatchMode=yes -o ControlMaster=auto -o "ControlPath=$HOME/.ssh/cm-%C"
          -o ControlPersist=30m -o ServerAliveInterval=30 -o ServerAliveCountMax=4)

# Runs in a remote login shell, so Slurm's environment is loaded; prints key=value lines.
remote_script=$(cat <<EOF
job=$(printf %q "$job") log=$(printf %q "$log") done_re=$(printf %q "$done_re")
case \$log in "~/"*) log="\$HOME/\${log#"~/"}" ;; esac
if [ -n "\$job" ]; then
  echo "state=\$(sacct -j "\$job" -X -n -P --format=State,ExitCode,Elapsed 2>/dev/null | head -1)"
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
  ssh "${ssh_opts[@]}" "$host" bash -s <<<"log=$(printf %q "$log"); case \$log in \"~/\"*) log=\"\$HOME/\${log#\"~/\"}\" ;; esac; tail -n 5 \"\$log\"" 2>/dev/null
}

failures=0
while :; do
  reply=$(ssh "${ssh_opts[@]}" "$host" bash -l -s <<<"$remote_script" 2>/dev/null)
  if [ "$(field ok)" != 1 ]; then
    failures=$((failures + 1))
    if [ "$failures" -ge 10 ]; then
      echo "$host: no answer after $failures tries"; exit 2
    fi
    sleep "$interval"; continue
  fi
  failures=0
  state=$(field state) age=$(field age) matched=$(field done)

  if [ -n "$matched" ]; then
    echo "$host: finished: $matched"; log_tail; exit 0
  fi
  if [ -n "$job" ] && [ -n "$state" ]; then
    case ${state%%|*} in
      PENDING|RUNNING|REQUEUED|RESIZING|SUSPENDED|CONFIGURING|COMPLETING) ;;
      *) echo "$host: job $job finished: $state"; log_tail; exit 0 ;;
    esac
  fi
  if [ "$stall_min" -gt 0 ] && [ -n "$age" ] && [ "$age" -gt $((stall_min * 60)) ] \
      && { [ -z "$job" ] || [ "${state%%|*}" = RUNNING ]; }; then
    echo "$host: stalled: $log unchanged for $((age / 60)) min${state:+ (job $job ${state%%|*})}"
    log_tail; exit 1
  fi
  sleep "$interval"
done
