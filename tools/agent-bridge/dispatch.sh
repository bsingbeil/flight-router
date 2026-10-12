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
usage: dispatch.sh --lane <name> --task <task-id> [--series <s>] [--eta <minutes>] [--message-file <path>] [--wait] [--no-preflight] [--force] [--force-shared-checkout] <message>...

the brief is the positional <message>..., or --message-file <path> instead.

options:
  --lane NAME       lane name (passed to `ask-pi -t <lane>`)
  --task ID         task id this dispatch is for (free text, e.g. a tasks/ slug)
  --series NAME     optional series/campaign label, carried into the record
  --eta MINUTES     minutes until deadline (default: 30)
  --message-file PATH
                    read the brief from PATH (mutually exclusive with a
                    positional message; a missing or empty file is refused)
  --wait            block until the worker exits, print the last 20 lines of
                    the dispatch log, and exit with the worker's exit code.
                    Without --wait the command returns as soon as the worker is
                    launched — redirect to a FILE, not a pipe: the detached
                    worker inherits stdout and holds a pipe open.
  --no-preflight    skip the model-API reachability check silently
  --force           dispatch past the 2-Pi ceiling anyway (warns loudly)
  --force-shared-checkout
                    dispatch a second Pi lane onto THIS working tree anyway.
                    Deliberately separate from --force: the ceiling is a
                    calibration guess, a shared checkout is a data-loss risk.
  -h, --help        this

Refuses (writing no record and launching nothing):
  exit 2  bad arguments (no brief, both a file and a positional message, a
          missing or empty --message-file, a missing --lane/--task, a
          non-integer --eta)
  exit 3  another unfinished Pi dispatch is already running against this same
          working tree — ADR 0086 makes a git worktree mandatory per parallel lane
  exit 4  the 2-Pi ceiling is already reached (ADR 0086; Pi only — nothing else
          writes dispatch records today)
  exit 5  the worker cannot reach its model's API base URL (proxy or network)
  exit 6  --wait only: the worker is gone and its record never closed, or the
          record closed with no exit code — the worker's fate is unknown

Prints the record path (line 1) and the ask-pi pid (line 2).
With --wait the exit code is the worker's (0, or whatever ask-pi returned); a
run that prints no record path refused before launch, so the exit code is
dispatch.sh's own (2, 3, 4 or 5); exit 6 means the worker's fate is unknown.
EOF
}

lane=""; task=""; series=""; eta=30; force=0; force_shared=0; message_file=""; do_wait=0; no_preflight=0; args=()
while [ $# -gt 0 ]; do
  case "$1" in
    --lane)   lane="${2:?--lane needs a value}"; shift 2 ;;
    --task)   task="${2:?--task needs a value}"; shift 2 ;;
    --series) series="${2:?--series needs a value}"; shift 2 ;;
    --eta)    eta="${2:?--eta needs a value}"; shift 2 ;;
    --message-file)
      [ $# -ge 2 ] && [ -n "$2" ] || { echo "dispatch.sh: --message-file needs a value" >&2; exit 2; }
      message_file="$2"; shift 2 ;;
    --wait)   do_wait=1; shift ;;
    --no-preflight) no_preflight=1; shift ;;
    --force)  force=1; shift ;;
    --force-shared-checkout) force_shared=1; shift ;;
    -h|--help) usage; exit 0 ;;
    --) shift; args+=("$@"); break ;;
    *) args+=("$1"); shift ;;
  esac
done

# The brief is either a file or a positional message, never both, and never
# empty — all three are argument errors, refused here before any gate reads the
# records or anything at all is written.
args_str="${args[*]-}"
if [ -n "$message_file" ]; then
  [ -z "${args_str//[[:space:]]/}" ] || {
    echo "dispatch.sh: --message-file and a positional message are mutually exclusive" >&2
    usage >&2; exit 2
  }
  if [ ! -r "$message_file" ] || [ -d "$message_file" ]; then
    echo "dispatch.sh: --message-file: not a readable regular file: ${message_file}" >&2; exit 2
  fi
  message="$(cat "$message_file" 2>/dev/null || true)"
  [ -n "${message//[[:space:]]/}" ] || {
    echo "dispatch.sh: --message-file: ${message_file} is empty" >&2; exit 2
  }
else
  message="$args_str"
  [ -n "${message//[[:space:]]/}" ] || { echo "dispatch.sh: message required" >&2; usage >&2; exit 2; }
fi

# A brief that starts with `-`, `--` or `@` is parsed by pi as an option or a file
# argument, not a message, so it never reaches the worker. Prefixing a newline
# makes it a positional message to the same parser. Markdown task files open with
# `---` frontmatter, so with --message-file this is the normal case, not an edge.
case "$message" in -*|@*) message=$'\n'"$message" ;; esac
[ -n "$lane" ] || { echo "dispatch.sh: --lane required" >&2; exit 2; }
[ -n "$task" ] || { echo "dispatch.sh: --task required" >&2; exit 2; }
case "$eta" in ''|*[!0-9]*) echo "dispatch.sh: --eta must be an integer number of minutes" >&2; exit 2 ;; esac

# Resolve a symlink chain to the real file before locating lib/: run through a
# link in ~/bin, $BASH_SOURCE is the link, not the checkout that holds lib/.
# Inline, because no helper can be sourced until we know where we are, and
# portable: macOS has no `readlink -f`. The same block belongs at the top of
# every bridge script that locates its siblings; keep the copies identical.
_self="${BASH_SOURCE[0]}"
while [ -L "$_self" ]; do
  _self_dir="$(CDPATH= cd -P "$(dirname "$_self")" && pwd)"
  _self="$(readlink "$_self")"
  case "$_self" in /*) ;; *) _self="${_self_dir}/${_self}" ;; esac
done
script_dir="$(CDPATH= cd -P "$(dirname "$_self")" && pwd)"
source "${script_dir}/lib/repo-root.sh"
# Needed before the in-flight gate below: it converts the record's `deadline`
# (or its mtime) to an epoch.
source "${script_dir}/lib/portable-date.sh"

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

# Effective model — the one pi actually runs with. PI_BRIDGE_MODEL is only the
# override: unset, pi uses its own configured default, and the record must say
# which model that is, not "". Resolve that default here at dispatch time; do
# NOT pass --model to pi — the default is pi's business, the record just has to
# be honest. Read only defaultProvider/defaultModel from settings.json here —
# models.json holds a plaintext API key, so the preflight below reads only the
# provider's `baseUrl` from it and never the key.
model="${PI_BRIDGE_MODEL:-}"
if [ -z "$model" ]; then
  pi_settings="${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}/settings.json"
  provider="$(jq -r '.defaultProvider // empty' "$pi_settings" 2>/dev/null || true)"
  default_model="$(jq -r '.defaultModel // empty' "$pi_settings" 2>/dev/null || true)"
  if [ -n "$provider" ] && [ -n "$default_model" ]; then
    model="${provider}/${default_model}"
  fi
fi

# ---- preflight: can the worker reach its model's API? --------------------------
# Runs BEFORE the ADR 0086 gate scan and before any record is written. That order
# matters: the curl below can take up to 10 s, and if it sat between the gate scan
# and the record write it would widen the gate's check-then-act window enough for
# two dispatches to both pass the scan. A refusal here still leaves nothing behind.
# curl inherits this process's environment, which approximates the worker's route
# (curl and Pi's HTTP client do not read proxy variables identically; --no-preflight
# is the documented escape). Any HTTP status (401 included) is a response and counts
# as reachable; the 2026-10-10 failure was curl exit 35, connection reset, no response.
# DISPATCH_PREFLIGHT_URL short-circuits the lookup and is what the tests use.
preflight_url="${DISPATCH_PREFLIGHT_URL:-}"
if [ "$no_preflight" = 0 ]; then
  if [ -z "$preflight_url" ]; then
    preflight_provider=""
    case "$model" in */*) preflight_provider="${model%%/*}" ;; esac
    if [ -n "$preflight_provider" ]; then
      pi_models="${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}/models.json"
      preflight_url="$(jq -r --arg p "$preflight_provider" '.providers[$p].baseUrl // empty' "$pi_models" 2>/dev/null || true)"
    fi
  fi
  if [ -z "$preflight_url" ]; then
    echo "dispatch.sh: preflight skipped — no API base URL known for model '${model}'" >&2
  else
    preflight_rc=0
    preflight_err="$(curl -q -sS -o /dev/null --max-time 10 -- "$preflight_url" 2>&1)" || preflight_rc=$?
    if [ "$preflight_rc" != 0 ]; then
      {
        echo "dispatch.sh: refusing — the worker cannot reach its model's API before launch."
        echo "    model: ${model}"
        echo "    url:   ${preflight_url}"
        echo "    error: curl exit ${preflight_rc}: ${preflight_err}"
        echo "  Any HTTP status (401 counts) means reachable; no response does not."
        echo "  Next check: the same request with the proxy bypassed (it answered in 0.14 s on 2026-10-10):"
        echo "    curl --noproxy '*' -sS -o /dev/null -m 10 '${preflight_url}'"
        echo "  If that answers, add the host to NO_PROXY (and no_proxy) before re-dispatching."
      } >&2
      exit 5
    fi
  fi
fi

# ---- the two ADR 0086 concurrency rules ---------------------------------------
# Both are checked HERE, before any record is written and before the launching
# subshell exists, so a refusal leaves nothing behind to clean up.
#
# In flight means: this record has no `finished`, AND its worker is still alive.
# If the launching subshell itself is killed (SIGTERM/SIGHUP to it, a reboot)
# nothing writes `finished`; without the liveness check one such loss would
# hold the gate shut until a human deleted files by hand.
#
# A record with no pid yet is the half-second between dispatch.sh's first write
# and the subshell publishing the pid. `record_in_flight` below holds it until
# its deadline (or a day from its mtime when the deadline is unreadable), then
# releases it — see that function for the full predicate.
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

# A record is in flight when it has no `finished` AND its worker is not provably
# gone. A live pid is the proof. A record written before the pid was known (the
# parent writes the pid a moment later, and a crash in that window leaves it
# null) is held only until its own `deadline`, or a day past its mtime when the
# deadline is missing or unreadable: either way a pid-less open record stops
# holding the gate, because past that it can never prove it is alive.
now_epoch="$(date -u +%s)"
file_mtime() { # <file> -> epoch seconds, empty if unavailable
  # GNU first: BSD `stat -c` fails cleanly with no stdout, but GNU `stat -f %m`
  # reads -f as --file-system and prints a filesystem block, so the old order put
  # junk in $bound on Linux and the arithmetic below would abort.
  stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null || true
}
rif_pid=""        # the effective pid the last record_in_flight() call found
rif_reason=""     # live-pid | pidfile | young-pidless | no-deadline
record_in_flight() { # <record file>
  local rec="$1" finished pid dl dl_epoch pf bound
  rif_pid=""; rif_reason=""
  finished="$(record_field "$rec" finished)"
  [ -z "$finished" ] || [ "$finished" = null ] || return 1
  pid="$(record_field "$rec" pid)"
  # A pid-less record whose worker is alive: the sibling pid file is written for
  # the worker's whole lifetime, so use it before the deadline rule. This covers
  # a failed pid write that left the initial (pid-less) record in place.
  if [ -z "$pid" ] || [ "$pid" = null ]; then
    pf="$(dirname "$rec")/.$(basename "$rec" .json).pid"
    if [ -s "$pf" ]; then
      pid="$(cat "$pf" 2>/dev/null || true)"
      [ -n "$pid" ] && rif_reason="pidfile"
    fi
  fi
  if [ -n "$pid" ] && [ "$pid" != null ]; then
    if kill -0 "$pid" 2>/dev/null; then
      rif_pid="$pid"
      [ -n "$rif_reason" ] || rif_reason="live-pid"
      return 0
    fi
    return 1                                   # worker is gone: stale record
  fi
  dl="$(record_field "$rec" deadline)"
  dl_epoch=""
  if [ -n "$dl" ] && [ "$dl" != null ]; then
    dl_epoch="$(epoch_from_iso "$dl")"
  fi
  # An empty or null deadline is never handed to GNU date (its `-d ""` means
  # today's 00:00, which would release the record on Linux); an unparseable one
  # comes back empty from epoch_from_iso. All three are bounded by the record's
  # mtime + 24h instead, so nothing can refuse a tree forever — and the refusal
  # note below says so, rather than claiming a deadline it could not read.
  if [ -z "$dl_epoch" ]; then
    bound="$(file_mtime "$rec")"
    case "$bound" in ''|*[!0-9]*) bound="" ;; esac
    if [ -n "$bound" ] && [ "$((bound + 86400))" -lt "$now_epoch" ]; then
      return 1
    fi
    rif_reason="no-deadline"
    return 0
  fi
  if [ "$dl_epoch" -lt "$now_epoch" ]; then
    return 1
  fi
  rif_reason="young-pidless"
  return 0
}

pi_in_flight=0          # how many Pi dispatches are live right now
blocking_lane=""        # a live one already on THIS working tree, if any
blocking_record=""
blocking_pid=""
blocking_reason=""
while IFS= read -r rec; do
  [ -n "$rec" ] || continue
  record_in_flight "$rec" || continue
  [ "$(record_field "$rec" worker)" = "pi" ] || continue
  pi_in_flight=$((pi_in_flight + 1))
  rec_tree="$(record_field "$rec" worktree)"
  # A record written before dispatch.sh recorded its working tree cannot prove it
  # is somewhere else, so it blocks. The conservative reading is the safe one for
  # the rule whose failure mode is two unattended agents writing one checkout.
  if [ -z "$rec_tree" ] || [ "$rec_tree" = null ] || [ "$rec_tree" = "$this_tree" ]; then
    blocking_lane="$(record_field "$rec" lane)"
    blocking_record="$rec"
    blocking_pid="$rif_pid"
    blocking_reason="$rif_reason"
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
      if [ "$blocking_reason" != live-pid ]; then
        blocking_deadline="$(record_field "$blocking_record" deadline)"
        case "$blocking_reason" in
          pidfile)
            echo "    note:   the record has no pid but its worker ${blocking_pid} is alive (read from the sibling .pid file)." ;;
          young-pidless)
            echo "    note:   the record has no pid yet — it is younger than its deadline (${blocking_deadline}), so it is held in case the worker is still starting." ;;
          no-deadline)
            echo "    note:   the record has no pid and no readable deadline — held for up to a day from its last write, then released." ;;
        esac
      fi
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
        record_in_flight "$r" || continue
        p="$rif_pid"; [ -n "$p" ] || p="$(record_field "$r" pid)"
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
  # Atomic AND conditional: readers (the gate, orchestrator-count.sh, the parent's
  # pid poll) must never see a truncated file, so the record is written to a temp
  # and renamed into place. And a write that FAILED must not be renamed over the
  # good record — an unconditional `mv` turned a full disk or a killed `cat` into
  # an unreadable open record that refused the tree to every later dispatch.
  local write_rc=0
  if cat > "${record_path}.tmp.$$" <<JSON
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
  then
    mv -f "${record_path}.tmp.$$" "$record_path" || write_rc=$?
  else
    write_rc=$?
  fi
  if [ "$write_rc" != 0 ]; then
    rm -f "${record_path}.tmp.$$"
    printf 'dispatch.sh: record write failed (exit %s); previous record left intact: %s\n' \
      "$write_rc" "$record_path" >> "$log_path" 2>/dev/null || true
    echo "dispatch.sh: WARNING — could not write ${record_path}; previous record left intact" >&2
    return 1
  fi
}

# Write the initial in-flight record BEFORE launching anything, so a record
# always exists once dispatch.sh returns. The pid is not yet known here — it
# belongs to a process we haven't started. Once launch happens, the SUBSHELL
# below is the only writer of this record from here on: it rewrites the pid
# in immediately, then rewrites finished/exit_code once when the worker
# exits. The parent (this process) never writes the record again — that is
# what caused the race: a fast-finishing worker's completion write used to
# get overwritten by the parent's own trailing "in-flight" write.
# Truncate the log once, then have the worker append: the subshell also appends
# a failed-write line, and two independent `>` offsets would overwrite it. The
# truncate runs before the first record write, so a failure here leaves no
# open record behind to hold the tree.
: > "$log_path"
write_record "null" "null" "null"
(
  # This subshell's one job after launching the worker is to write the closing
  # record, so it must reach that write after every failing command — not just
  # status 0. It inherits `set -e` from the script, which is what broke it: a
  # bare `wait` on a non-zero worker (ticket 263: pi exited on a 400) was a
  # failing simple command, so the shell exited before `exit_code=$?` and before
  # the closing write_record. The record kept "finished": null and
  # "exit_code": null, which orchestrator-count.sh reported as DEAD on every run.
  # Still uncovered: `set -u` is inherited (an unbound variable aborts), and a
  # signal to this subshell is not trapped. `set +e` covers the 263 path.
  set +e
  "$ask_pi" -t "$lane" "$message" >> "$log_path" 2>&1 &
  worker_pid=$!
  echo "$worker_pid" > "$pid_file"
  write_record "$worker_pid" "null" "null"
  # `||` too: belt-and-braces if `set +e` above is ever removed.
  exit_code=0
  wait "$worker_pid" || exit_code=$?
  finished_iso="$(iso_from_epoch "$(date -u +%s)")"
  write_record "$worker_pid" "$finished_iso" "$exit_code"
  rm -f "$pid_file"
) &
disown 2>/dev/null || true

# Hold the machine awake while --wait waits. `-w $$` ties caffeinate's life to
# this process, so it exits on its own when the wait is over — no kill needed
# (and killing it races its own startup, as the test caught).

# worker_pid may still be empty if the subshell hasn't scheduled yet — or because
# the worker failed fast and the subshell already finished and removed the pid
# file. The record carries the pid from its first write, so poll that too, and
# treat a missing pid file as "not yet", never as a failed read: under `set -e` a
# bare `cat` on the rm'd file aborted dispatch.sh with nothing on stdout even
# though the worker ran and its record exists.
worker_pid=""
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if [ -s "$pid_file" ]; then
    worker_pid="$(cat "$pid_file" 2>/dev/null || true)"
  fi
  if [ -z "$worker_pid" ]; then
    worker_pid="$(record_field "$record_path" pid)"
    [ "$worker_pid" = null ] && worker_pid=""
  fi
  [ -n "$worker_pid" ] && break
  sleep 0.2
done

echo "$record_path"
echo "$worker_pid"

# Hold the machine awake while --wait waits, tied to the worker's pid so the hold
# lasts as long as the worker (not just this waiter). `-w` needs a pid; if the
# worker's was never published, fall back to our own.
if [ "$do_wait" = 1 ] && command -v caffeinate >/dev/null 2>&1; then
  caffeinate -i -w "${worker_pid:-$$}" >/dev/null 2>&1 &
fi

# Interrupting --wait stops the WAITER, not the worker: the worker is disowned
# and the record is its handle. Say so on the way out instead of dying silently.
if [ "$do_wait" = 1 ]; then
  trap "echo \"dispatch.sh: wait interrupted — worker ${worker_pid:-?} may still be running; poll the record: ${record_path}\" >&2; exit 130" INT TERM
fi

# --wait: the worker is a child of the detached subshell, not of this shell, so
# it cannot be reaped with `wait`. Its closing record is the signal that it has
# exited; poll for it, then report the code and the tail of the log. This is the
# intentional wait, not the inherited-stdout accident a pipe caller relies on.
#
# The record is guaranteed closed on the normal path, but `set -u` in the
# subshell and a failed closing write (the ticket-263 tests) can leave a dead
# worker with `finished: null`. Waiting forever would spin at 5 Hz and, with
# caffeinate, keep the Mac awake doing it: a dead worker gets a 5 s grace for its
# closing write, then exit 6. A closed record with no
# exit_code is unknown, never success.
if [ "$do_wait" = 1 ]; then
  gone_polls=0
  empty_pid_polls=0
  while :; do
    wait_finished="$(record_field "$record_path" finished || true)"
    if [ -n "$wait_finished" ] && [ "$wait_finished" != null ]; then break; fi
    # The pid may still be unknown if the pid file and the record's pid write both
    # lost. Re-read it here, and treat a worker that never becomes identifiable as
    # the same unknown-fate exit rather than an unbounded spin.
    if [ -z "$worker_pid" ]; then
      if [ -s "$pid_file" ]; then worker_pid="$(cat "$pid_file" 2>/dev/null || true)"; fi
      if [ -z "$worker_pid" ]; then
        worker_pid="$(record_field "$record_path" pid || true)"
        [ "$worker_pid" = null ] && worker_pid=""
      fi
    fi
    if [ -n "$worker_pid" ] && ! kill -0 "$worker_pid" 2>/dev/null; then
      gone_polls=$((gone_polls + 1))
      if [ "$gone_polls" -ge 25 ]; then
        echo "dispatch.sh: worker ${worker_pid} is gone and its record never closed — see ${log_path}" >&2
        tail -n 20 "$log_path"
        exit 6
      fi
    elif [ -z "$worker_pid" ]; then
      empty_pid_polls=$((empty_pid_polls + 1))
      if [ "$empty_pid_polls" -ge 25 ]; then
        echo "dispatch.sh: no worker pid was ever published and the record never closed — see ${log_path}" >&2
        tail -n 20 "$log_path"
        exit 6
      fi
    else
      gone_polls=0
      empty_pid_polls=0
    fi
    sleep 0.2
  done
  wait_rc="$(record_field "$record_path" exit_code || true)"
  if [ -z "$wait_rc" ] || [ "$wait_rc" = null ]; then
    echo "dispatch.sh: the record closed with no exit_code; the worker's fate is unknown — see ${log_path}" >&2
    tail -n 20 "$log_path"
    exit 6
  fi
  tail -n 20 "$log_path"
  exit "$wait_rc"
fi
