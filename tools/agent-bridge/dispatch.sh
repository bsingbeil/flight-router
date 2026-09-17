#!/usr/bin/env bash
# dispatch.sh — background a Pi task via ask-pi and leave a JSON record behind
# so a caller can poll it instead of blocking on ask-pi's normal synchronous
# call. ask-pi has no background mode; this wraps it. ask-pi's own watchdog
# ends a stalled run with exit 124, which lands in the record's exit_code.
#
#   dispatch.sh --lane scraper --task fanout-mints-unsellable-products \
#               --series storefront-fanout --eta 45 \
#               "fix the vendor_color_id gap, see tasks/inbox/006-..."
#
# Writes:
#   .claude/dispatch/<lane>-<timestamp>.log   (ask-pi stdout+stderr)
#   .claude/dispatch/<lane>-<timestamp>.json  (status record, updated on exit)
set -euo pipefail

usage() {
  cat <<'EOF'
usage: dispatch.sh --lane <name> --task <task-id> [--series <s>] [--eta <minutes>] <message>...

options:
  --lane NAME       lane name (passed to `ask-pi -t <lane>`)
  --task ID         task id this dispatch is for (free text, e.g. a tasks/ slug)
  --series NAME     optional series/campaign label, carried into the record
  --eta MINUTES     minutes until deadline (default: 30)
  -h, --help        this

Prints the record path (line 1) and the ask-pi pid (line 2).
EOF
}

lane=""; task=""; series=""; eta=30; args=()
while [ $# -gt 0 ]; do
  case "$1" in
    --lane)   lane="${2:?--lane needs a value}"; shift 2 ;;
    --task)   task="${2:?--task needs a value}"; shift 2 ;;
    --series) series="${2:?--series needs a value}"; shift 2 ;;
    --eta)    eta="${2:?--eta needs a value}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    --) shift; args+=("$@"); break ;;
    *) args+=("$1"); shift ;;
  esac
done

message="${args[*]-}"
[ -n "${message// }" ] || { echo "dispatch.sh: message required" >&2; usage >&2; exit 2; }
[ -n "$lane" ] || { echo "dispatch.sh: --lane required" >&2; exit 2; }
[ -n "$task" ] || { echo "dispatch.sh: --task required" >&2; exit 2; }
case "$eta" in ''|*[!0-9]*) echo "dispatch.sh: --eta must be an integer number of minutes" >&2; exit 2 ;; esac

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_dir}/lib/repo-root.sh"

# Resolve the MAIN checkout's root, not this worktree's own root — see
# lib/repo-root.sh. ADR 0086 requires --worktree for every parallel Pi lane,
# so dispatch.sh runs from inside a worktree far more often than not; if it
# wrote records under the worktree's own .claude/dispatch/, the watcher
# (orchestrator-count.sh, run from the main checkout under launchd) would
# never see them.
root="$(agent_bridge_root "$script_dir")"
dispatch_dir="${root}/.claude/dispatch"
mkdir -p "$dispatch_dir"

ask_pi="${script_dir}/ask-pi"
[ -x "$ask_pi" ] || ask_pi="ask-pi"   # fall back to PATH if not colocated

ts="$(date -u +%Y%m%dT%H%M%SZ)"
stem="${lane}-${ts}"
log_path="${dispatch_dir}/${stem}.log"
record_path="${dispatch_dir}/${stem}.json"
pid_file="${dispatch_dir}/.${stem}.pid"

source "${script_dir}/lib/portable-date.sh"

started_epoch="$(date -u +%s)"
started_iso="$(iso_from_epoch "$started_epoch")"
deadline_epoch=$((started_epoch + eta * 60))
deadline_iso="$(iso_from_epoch "$deadline_epoch")"

# JSON string escape: backslash and double-quote — good enough for the
# free-text fields accepted here (lane/task/series names, paths, model ids).
json_escape() {
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  printf '%s' "$s"
}

write_record() {
  local pid="$1" finished="$2" exit_code="$3"
  local pid_json="null" finished_json="null" exit_json="null"
  [ -n "$pid" ] && [ "$pid" != "null" ] && pid_json="$pid"
  [ "$finished" != "null" ] && finished_json="\"$(json_escape "$finished")\""
  [ "$exit_code" != "null" ] && exit_json="$exit_code"
  cat > "$record_path" <<JSON
{
  "lane": "$(json_escape "$lane")",
  "task": "$(json_escape "$task")",
  "series": "$(json_escape "$series")",
  "worker": "pi",
  "pid": ${pid_json},
  "model": "$(json_escape "${PI_BRIDGE_MODEL:-}")",
  "output_path": "$(json_escape "$log_path")",
  "started": "$(json_escape "$started_iso")",
  "eta_minutes": ${eta},
  "deadline": "$(json_escape "$deadline_iso")",
  "finished": ${finished_json},
  "exit_code": ${exit_json}
}
JSON
}

# Write the initial in-flight record BEFORE launching anything, so a record
# always exists once dispatch.sh returns. The pid is not yet known here — it
# belongs to a process we haven't started. Once launch happens, the SUBSHELL
# below is the only writer of this record from here on: it rewrites the pid
# in immediately, then rewrites finished/exit_code once when the worker
# exits. The parent (this process) never writes the record again — that is
# what caused the race: a fast-finishing worker's completion write used to
# get overwritten by the parent's own trailing "in-flight" write.
write_record "null" "null" "null"

# Launch ask-pi in the background inside a detached subshell that also waits
# on it, so the wait survives dispatch.sh itself returning. The subshell is a
# fork of this shell, so it inherits the functions/variables above — no need
# to redefine json_escape etc. It writes its own pid to pid_file, and to the
# record, so the parent can report the REAL worker pid, not the subshell's.
(
  "$ask_pi" -t "$lane" "$message" > "$log_path" 2>&1 &
  worker_pid=$!
  echo "$worker_pid" > "$pid_file"
  write_record "$worker_pid" "null" "null"
  wait "$worker_pid"
  exit_code=$?
  finished_iso="$(iso_from_epoch "$(date -u +%s)")"
  write_record "$worker_pid" "$finished_iso" "$exit_code"
  rm -f "$pid_file"
) &
disown 2>/dev/null || true

# Wait briefly for the subshell to publish the real worker pid, purely to
# report it on stdout below — the record file itself is not touched here.
worker_pid=""
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if [ -s "$pid_file" ]; then
    worker_pid="$(cat "$pid_file")"
    break
  fi
  sleep 0.2
done
# worker_pid may still be empty if the subshell hasn't scheduled yet — report
# that honestly rather than falling back to "$!" (the subshell's own pid,
# not the worker's).

echo "$record_path"
echo "$worker_pid"
