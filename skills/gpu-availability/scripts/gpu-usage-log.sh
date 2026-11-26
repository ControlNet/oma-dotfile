#!/usr/bin/env bash
# GPU usage recorder for a shared workstation, deployed by the gpu-availability skill to
# ~/.local/share/gpu-usage/gpu-usage-log.sh.
#
# usage: gpu-usage-log.sh install | uninstall | sample
#   install    add a cron entry that runs `sample` every minute (survives reboots, no root)
#   uninstall  remove that cron entry; the records stay
#   sample     read every GPU 6 times, 10 s apart, and append one line per GPU to
#              ~/.cache/gpu-usage/<date>.tsv:
#              epoch, index, max utilization %, max memory used MiB, memory total MiB,
#              users with compute processes (comma-separated, "-" for none)
# Records older than 14 days are deleted.
set -u
self=$HOME/.local/share/gpu-usage/gpu-usage-log.sh
data=$HOME/.cache/gpu-usage
marker="# gpu-usage-log (gpu-availability skill)"

case ${1:-} in
install)
  mkdir -p "$data"
  { crontab -l 2>/dev/null | grep -vF "$marker"
    echo "* * * * * bash $self sample >/dev/null 2>&1 $marker"; } | crontab -
  # Tell other agents on this machine what the cron entry is.
  if ! grep -qs "gpu-usage-log" "$HOME/AGENTS.md"; then
    [ -s "$HOME/AGENTS.md" ] || printf '# This machine\n\n' > "$HOME/AGENTS.md"
    printf '%s\n' "- A cron entry runs ~/.local/share/gpu-usage/gpu-usage-log.sh every minute to record GPU" \
      "  use in ~/.cache/gpu-usage (14 days), for the gpu-availability skill. Remove it with" \
      "  \`bash ~/.local/share/gpu-usage/gpu-usage-log.sh uninstall\`." >> "$HOME/AGENTS.md"
  fi
  ;;
uninstall)
  crontab -l 2>/dev/null | grep -vF "$marker" | crontab -
  ;;
sample)
  command -v nvidia-smi >/dev/null || exit 0
  mkdir -p "$data"
  exec 9>"$data/.lock"
  flock -n 9 || exit 0
  declare -A util mem total users index_of
  for round in 1 2 3 4 5 6; do
    while IFS=, read -r idx uuid u m t; do
      idx=${idx// /} uuid=${uuid// /} u=${u// /} m=${m// /} t=${t// /}
      [[ $u =~ ^[0-9]+$ ]] || u=0
      [[ $m =~ ^[0-9]+$ ]] || m=0
      index_of[$uuid]=$idx total[$idx]=$t
      [ "$u" -gt "${util[$idx]:-0}" ] && util[$idx]=$u
      [ "$m" -gt "${mem[$idx]:-0}" ] && mem[$idx]=$m
    done < <(nvidia-smi --query-gpu=index,uuid,utilization.gpu,memory.used,memory.total \
               --format=csv,noheader,nounits)
    while IFS=, read -r uuid pid; do
      uuid=${uuid// /} pid=${pid// /}
      [ -n "$pid" ] || continue
      idx=${index_of[$uuid]:-}
      [ -n "$idx" ] || continue
      user=$(ps -o user= -p "$pid" 2>/dev/null | tr -d ' ')
      user=${user:-pid$pid}
      case ",${users[$idx]:-}," in
        *",$user,"*) ;;
        *) users[$idx]=${users[$idx]:+${users[$idx]},}$user ;;
      esac
    done < <(nvidia-smi --query-compute-apps=gpu_uuid,pid --format=csv,noheader 2>/dev/null)
    [ "$round" -lt 6 ] && sleep 10
  done
  now=$(date +%s)
  for idx in $(printf '%s\n' "${!total[@]}" | sort -n); do
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$now" "$idx" "${util[$idx]:-0}" "${mem[$idx]:-0}" \
      "${total[$idx]}" "${users[$idx]:--}"
  done >> "$data/$(date +%F).tsv"
  find "$data" -name '*.tsv' -mtime +14 -delete
  ;;
*)
  sed -n '5,8p' "$0" >&2
  exit 64
  ;;
esac
