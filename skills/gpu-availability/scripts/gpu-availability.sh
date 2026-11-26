#!/usr/bin/env bash
# Report which GPUs on shared workstations have been idle, from a recorder on each machine.
# Every ssh call has a timeout: ConnectTimeout does not cover a ProxyCommand.
#
# usage: gpu-availability.sh [--hours N] [<ssh-host>...]
#   --hours N  how many whole hours a GPU must have been idle to count as free (default 6)
#   hosts      default: the SSH targets of `herdr machine list`
#
# On a host without the recorder (gpu-usage-log.sh, run by cron every minute), or with an older
# copy, the script installs it and reports the current state until history builds up.
# A minute counts as busy when the GPU had a compute process, more than 1 GiB of memory in use
# or more than 10% utilization.
set -u
here=$(cd "$(dirname "$0")" && pwd)
recorder=$here/gpu-usage-log.sh
hours=6
case ${1:-} in --hours) hours=${2:?}; shift 2 ;; esac
[[ $hours =~ ^[1-9][0-9]*$ ]] || { sed -n '5,7p' "$0" >&2; exit 64; }
if [ $# -eq 0 ]; then
  mapfile -t hosts < <(herdr machine list --json 2>/dev/null \
    | python3 -c 'import json,sys; [print(m["target"]) for m in json.load(sys.stdin) if m.get("enabled")]')
  [ ${#hosts[@]} -gt 0 ] || { echo "no hosts given and no Herdr machines" >&2; exit 64; }
else
  hosts=("$@")
fi
mapfile -t hosts < <(printf '%s\n' "${hosts[@]}" | awk '!seen[$0]++')

ssh_opts=(-q -T -o BatchMode=yes -o ConnectTimeout=15 -o ControlMaster=auto
          -o "ControlPath=$HOME/.ssh/cm-%C" -o ControlPersist=10m -o ServerAliveInterval=30)
want=$(sha256sum "$recorder" | cut -d' ' -f1)

# Remote side: prints "now,..." per GPU, "hist,..." per GPU from the records in the window,
# "meta,<first record in the window>,<last record at all>" and "clock,...". The users field is
# last and may itself contain commas.
query=$(cat <<EOF
hours=$hours
EOF
)$(cat <<'EOF'

now=$(date +%s); cut=$((now - hours * 3600))
declare -A index_of users
while IFS=, read -r idx uuid; do index_of[${uuid// /}]=${idx// /}; done \
  < <(nvidia-smi --query-gpu=index,uuid --format=csv,noheader)
while IFS=, read -r uuid pid; do
  pid=${pid// /}; idx=${index_of[${uuid// /}]:-}; [ -n "$pid" ] && [ -n "$idx" ] || continue
  u=$(ps -o user= -p "$pid" 2>/dev/null | tr -d ' '); u=${u:-pid$pid}
  case ",${users[$idx]:-}," in *",$u,"*) ;; *) users[$idx]=${users[$idx]:+${users[$idx]},}$u ;; esac
done < <(nvidia-smi --query-compute-apps=gpu_uuid,pid --format=csv,noheader 2>/dev/null)
nvidia-smi --query-gpu=index,name,utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits \
  | while IFS=, read -r idx name u m t; do
      idx=${idx// /}; echo "now,$idx,${name# },${u// /},${m// /},${t// /},${users[$idx]:--}"
    done
files=$(find ~/.cache/gpu-usage -name '*.tsv' -mtime -$((hours / 24 + 2)) 2>/dev/null | sort)
if [ -n "$files" ]; then
  awk -F'\t' -v cut="$cut" '{ if ($1 > last) last = $1 } $1 >= cut {
      i = $2; n[i]++; if (first == "" || $1 < first) first = $1
      if ($6 != "-" || $4 > 1024 || $3 > 10) { b[i]++; if ($1 > lb[i]) { lb[i] = $1; who[i] = $6 } }
    }
    END { for (i in n) printf "hist,%s,%d,%d,%d,%s\n", i, n[i], b[i], lb[i], who[i]
          if (last != "") printf "meta,%d,%d\n", first, last }' $files
fi
echo "clock,$now"
EOF
)

# Local side: turns the remote lines into the report.
report=$(cat <<'PY'
import sys
host, hours, note = sys.argv[1], float(sys.argv[2]), sys.argv[3]
now, hist, meta, clock = {}, {}, None, None

def num(text):
    # nvidia-smi prints [N/A] or [Not Supported] for some values (MIG, some boards).
    return int(text) if text.strip().isdigit() else 0

for line in sys.stdin.read().splitlines():
    kind = line.split(",", 1)[0]
    if kind == "now":
        _, idx, name, u, m, t, users = line.split(",", 6)
        now[int(idx)] = (name, num(u), num(m), num(t), users)
    elif kind == "hist":
        _, idx, n, b, last_busy, who = line.split(",", 5)
        hist[int(idx)] = (int(n), int(b), int(last_busy), who)
    elif kind == "meta":
        meta = tuple(int(v) for v in line.split(",")[1:3])
    elif kind == "clock":
        clock = int(line.split(",")[1])

def ago(seconds):
    return f"{seconds / 3600:.1f} h" if seconds >= 3600 else f"{seconds // 60} min"

span = (clock - meta[0]) if meta and meta[0] else 0
stale = meta is not None and clock - meta[1] > 180
names = sorted({v[0] for v in now.values()})
free = []
free_now = []
lines = []
for idx in sorted(now, reverse=True):
    name, u, m, t, users = now[idx]
    busy_now = users != "-" or m > 1024 or u > 10
    n, b, last_busy, who = hist.get(idx, (0, 0, 0, ""))
    if n and b:
        history = f"busy {100 * b // n}% of {ago(span)}, last {ago(clock - last_busy)} ago"
        history += f" by {who}" if who != "-" else ""
    elif n:
        history = f"idle for all {ago(span)} recorded"
    else:
        history = "no history yet"
    if n and not b and not busy_now and not stale:
        free.append(str(idx))
    if not busy_now:
        free_now.append(str(idx))
    state = f"now {u}% {m}/{t} MiB" + (f" ({users})" if users != "-" else "")
    lines.append(f"  gpu {idx}  {history}; {state}")
short = span < hours * 3600 - 300
cover = f"; history covers {ago(span)} of {hours:g} h" if span and short else ""
if stale:
    cover += f"; recorder stopped {ago(clock - meta[1])} ago"
if short or stale:
    cover += f"; free right now [{','.join(free_now) or 'none'}]"
print(f"{host} ({len(now)}x {', '.join(names)}): idle GPUs [{','.join(free) or 'none'}]{cover}{note}")
print("\n".join(lines))
PY
)

check() {
  local host=$1 have note="" out
  have=$(timeout 40 ssh "${ssh_opts[@]}" "$host" \
    'command -v nvidia-smi >/dev/null || { echo no-gpu; exit; }; sha256sum ~/.local/share/gpu-usage/gpu-usage-log.sh 2>/dev/null | cut -d" " -f1; crontab -l 2>/dev/null | grep -c "gpu-usage-log (gpu-availability skill)"' \
    < /dev/null 2>/dev/null)
  if [ -z "$have" ]; then echo "$host: unreachable"; return; fi
  if [ "$have" = no-gpu ]; then echo "$host: no nvidia-smi"; return; fi
  if [ "$(sed -n 1p <<<"$have")" != "$want" ] || [ "$(sed -n 2p <<<"$have")" = 0 ]; then
    # Write a new file and rename it: cron may be running the old copy, and bash reads a
    # script as it goes.
    if timeout 60 ssh "${ssh_opts[@]}" "$host" 'mkdir -p ~/.local/share/gpu-usage &&
        cat > ~/.local/share/gpu-usage/gpu-usage-log.sh.new &&
        mv -f ~/.local/share/gpu-usage/gpu-usage-log.sh.new ~/.local/share/gpu-usage/gpu-usage-log.sh &&
        bash ~/.local/share/gpu-usage/gpu-usage-log.sh install' < "$recorder" 2>/dev/null; then
      note=" (recorder installed now)"
    else
      note=" (installing the recorder failed)"
    fi
  fi
  out=$(timeout 60 ssh "${ssh_opts[@]}" "$host" bash -s <<<"$query" 2>/dev/null)
  if ! grep -q '^now,' <<<"$out"; then echo "$host: nvidia-smi query failed or timed out$note"; return; fi
  python3 -c "$report" "$host" "$hours" "$note" <<<"$out"
}

tmp=$(mktemp -d)
for host in "${hosts[@]}"; do check "$host" > "$tmp/$host" & done
wait
for host in "${hosts[@]}"; do cat "$tmp/$host"; done
rm -rf "$tmp"
