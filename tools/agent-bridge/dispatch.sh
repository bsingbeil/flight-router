#!/usr/bin/env bash
# dispatch.sh — background a Pi task via ask-pi and leave a JSON record behind
# so a caller can poll it instead of blocking on ask-pi's normal synchronous
# call. ask-pi has no timeout and no background mode; this wraps it.
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
  --force           dispatch past the 2-Pi ceiling anyway (warns loudly)
  --force-shared-checkout
                    dispatch a second Pi lane onto THIS working tree anyway.
                    Deliberately separate from --force: the ceiling is a
                    calibration guess, a shared checkout is a data-loss risk.
  -h, --help        this

Refuses (writing no record and launching nothing):
  exit 3  another unfinished Pi dispatch is already running against this same
          working tree — ADR 0086 makes a git worktree mandatory per parallel lane
  exit 4  the 2-Pi ceiling is already reached (ADR 0086; Pi only — nothing else
          writes dispatch records today)

Prints the record path (line 1) and the ask-pi pid (line 2).
EOF
}

lane=""; task=""; series=""; eta=30; force=0; force_shared=0; args=()
while [ $# -gt 0 ]; do
  case "$1" in
    --lane)   lane="${2:?--lane needs a value}"; shift 2 ;;
    --task)   task="${2:?--task needs a value}"; shift 2 ;;
    --series) series="${2:?--series needs a value}"; shift 2 ;;
    --eta)    eta="${2:?--eta needs a value}"; shift 2 ;;
    --force)  force=1; shift ;;
    --force-shared-checkout) force_shared=1; shift ;;
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

# ---- the two ADR 0086 concurrency rules ---------------------------------------
# Both are checked HERE, before any record is written and before the launching
# subshell exists, so a refusal leaves nothing behind to clean up.
#
# In flight means: this record has no `finished`, AND its worker is still alive.
# A crashed worker never writes `finished`, and without the liveness check one
# crash would hold the gate shut until a human deleted files by hand.
#
# A record with no pid yet is the half-second between dispatch.sh's first write
# and the subshell publishing the pid — counted as in flight, deliberately: the
# safe reading of "I can't tell yet" is "something is starting".
#
# Records are machine-local and gitignored (ADR 0086), so this only ever sees
# what is on this machine's disk. That is the whole scope of the rule.

# The working tree this dispatch is being launched from — NOT `root`, which is
# the shared main checkout every worktree resolves to.
this_tree="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

record_field() { # <record file> <key> — our writer emits one "key": value per line.
  sed -n "s/^[[:space:]]*\"$2\":[[:space:]]*//p" "$1" | head -1 \
    | sed -e 's/^"//' -e 's/",\{0,1\}[[:space:]]*$//' -e 's/,[[:space:]]*$//'
}

pi_in_flight=0          # how many Pi dispatches are live right now
blocking_lane=""        # a live one already on THIS working tree, if any
blocking_record=""
while IFS= read -r rec; do
  [ -n "$rec" ] || continue
  finished="$(record_field "$rec" finished)"
  [ -z "$finished" ] || [ "$finished" = null ] || continue
  pid="$(record_field "$rec" pid)"
  if [ -n "$pid" ] && [ "$pid" != null ]; then
    kill -0 "$pid" 2>/dev/null || continue     # worker is gone: stale record
  fi
  [ "$(record_field "$rec" worker)" = "pi" ] || continue
  pi_in_flight=$((pi_in_flight + 1))
  rec_tree="$(record_field "$rec" worktree)"
  # A record written before dispatch.sh recorded its working tree cannot prove it
  # is somewhere else, so it blocks. The conservative reading is the safe one for
  # the rule whose failure mode is two unattended agents writing one checkout.
  if [ -z "$rec_tree" ] || [ "$rec_tree" = null ] || [ "$rec_tree" = "$this_tree" ]; then
    blocking_lane="$(record_field "$rec" lane)"
    blocking_record="$rec"
  fi
done < <(find "$dispatch_dir" -maxdepth 1 -type f -name '*.json' 2>/dev/null | sort)

if [ -n "$blocking_lane" ]; then
  if [ "$force_shared" = 1 ]; then
    echo "dispatch.sh: ⚠ BYPASSING the worktree rule (--force-shared-checkout): lane '${blocking_lane}' is already running against ${this_tree}. Two unattended --approve agents on one checkout is how work gets clobbered (ADR 0086)." >&2
  else
    {
      echo "dispatch.sh: refusing — lane '${blocking_lane}' is already running against this same working tree:"
      echo "    tree:   ${this_tree}"
      echo "    record: ${blocking_record}"
      echo "  ADR 0086 makes a git worktree mandatory for every parallel Pi lane. Give this lane its own:"
      echo "    lane new ${lane} --worktree <branch> --owns <paths>"
      echo "  Or, if you have checked that it is genuinely safe: --force-shared-checkout"
    } >&2
    exit 3
  fi
fi

# Pi only, and said out loud: dispatch.sh is the only thing that writes dispatch
# records, and every one of them is worker="pi". The Sonnet half of ADR 0086's
# "two Pi plus two Sonnet" is unenforceable until Sonnet dispatches leave records
# too — enforcing half a rule silently would read as enforcing all of it.
PI_CEILING="${DISPATCH_PI_CEILING:-2}"
if [ "$pi_in_flight" -ge "$PI_CEILING" ]; then
  if [ "$force" = 1 ]; then
    echo "dispatch.sh: ⚠ BYPASSING the Pi ceiling (--force): ${pi_in_flight} already in flight, ceiling ${PI_CEILING}." >&2
  else
    {
      echo "dispatch.sh: refusing — ${pi_in_flight} Pi dispatches are already in flight and the ceiling is ${PI_CEILING}."
      echo "  Counting Pi only: nothing else writes dispatch records yet, so the Sonnet half of"
      echo "  ADR 0086's '2 Pi + 2 Sonnet' is not enforced here."
      echo "  The ceiling is a calibration guess (ADR 0086; task 031 sets the real one) — raise it"
      echo "  for one call with --force, or for a session with DISPATCH_PI_CEILING=<n>."
      echo "  In flight:"
      find "$dispatch_dir" -maxdepth 1 -type f -name '*.json' 2>/dev/null | sort | while IFS= read -r r; do
        f="$(record_field "$r" finished)"
        [ -z "$f" ] || [ "$f" = null ] || continue
        p="$(record_field "$r" pid)"
        if [ -n "$p" ] && [ "$p" != null ]; then kill -0 "$p" 2>/dev/null || continue; fi
        echo "    - $(record_field "$r" lane) (task $(record_field "$r" task), pid ${p}) in $(record_field "$r" worktree)"
      done
    } >&2
    exit 4
  fi
fi

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

# Effective model — the one pi actually runs with. PI_BRIDGE_MODEL is only the
# override: unset, pi uses its own configured default, and the record must say
# which model that is, not "". Resolve that default here at dispatch time; do
# NOT pass --model to pi — the default is pi's business, the record just has to
# be honest. Read only defaultProvider/defaultModel from settings.json (never
# models.json, which holds a plaintext API key).
model="${PI_BRIDGE_MODEL:-}"
if [ -z "$model" ]; then
  pi_settings="${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}/settings.json"
  provider="$(jq -r '.defaultProvider // empty' "$pi_settings" 2>/dev/null || true)"
  default_model="$(jq -r '.defaultModel // empty' "$pi_settings" 2>/dev/null || true)"
  if [ -n "$provider" ] && [ -n "$default_model" ]; then
    model="${provider}/${default_model}"
  fi
fi

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
  "worktree": "$(json_escape "$this_tree")",
  "pid": ${pid_json},
  "model": "$(json_escape "$model")",
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
