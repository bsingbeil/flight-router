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
  --eta MINUTES     minutes until deadline (default: 30). Digits are decimal:
                    `08` is 8 minutes, never octal. Its deadline also bounds
                    --wait (see below).
  --message-file PATH
                    read the brief from PATH (mutually exclusive with a
                    positional message; a missing or empty file is refused)
  --wait            block until the worker exits, print the last 20 lines of
                    the dispatch log, and exit with the worker's exit code.
                    Without --wait the command returns as soon as the worker is
                    launched. Redirect to FILES: a pipe as stdout or stderr is
                    refused (exit 2), because the detached worker's subshell holds
                    it open until the worker exits — or pass --wait instead.
                    The wait stops once the record's deadline has passed by
                    DISPATCH_WAIT_GRACE seconds (default 300), then exits 6:
                    ask-pi has no timeout, so an unbounded wait would outlive it.
  --reason TEXT     why this dispatch happened, carried into the record: `first`
                    (a ticket's first start), `sent-back` (the lander refused a
                    worker's finished work) or `worker-died` (the previous worker
                    never closed, or closed non-zero). `ticket.sh start` and
                    `ticket.sh redispatch` set it; `lands.tsv` counts send-backs
                    from it, so a worker that died is never counted as one.
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
          non-integer --eta), or stdout/stderr is a pipe without --wait
  exit 3  another unfinished Pi dispatch is already running against this same
          working tree — ADR 0086 makes a git worktree mandatory per parallel lane
  exit 4  the 2-Pi ceiling is already reached (ADR 0086; Pi only — nothing else
          writes dispatch records today)
  exit 5  the preflight cannot prove the worker will reach its model's API: no
          HTTP response (proxy or network), curl is not installed, or the
          provider's baseUrl is not an http(s) URL string
  exit 6  --wait only: the worker is gone and its record never closed, the
          record closed with no exit code, or the record's deadline passed by
          DISPATCH_WAIT_GRACE seconds — the worker's fate is unknown

Prints the record path (line 1) and the ask-pi pid (line 2).
With --wait the exit code is the worker's (0, or whatever ask-pi returned); a
run that prints no record path refused before launch, so the exit code is
dispatch.sh's own (2, 3, 4 or 5); exit 6 means the worker's fate is unknown. A
--wait that gave up at the deadline leaves the worker running: the record is
still its handle.
EOF
}

lane=""; task=""; series=""; reason=""; eta=30; force=0; force_shared=0; message_file=""; do_wait=0; no_preflight=0; args=()
while [ $# -gt 0 ]; do
  case "$1" in
    --lane)   lane="${2:?--lane needs a value}"; shift 2 ;;
    --task)   task="${2:?--task needs a value}"; shift 2 ;;
    --series) series="${2:?--series needs a value}"; shift 2 ;;
    --reason) reason="${2:?--reason needs a value}"; shift 2 ;;
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
# Digits only, then read as DECIMAL. A bare `$((eta * 60))` later treats a
# leading zero as octal: `08`/`09` abort the script (the ticket's audit) and
# `010` silently means 8 minutes. 10# is bash's explicit-decimal base.
case "$eta" in ''|*[!0-9]*) echo "dispatch.sh: --eta must be an integer number of minutes" >&2; exit 2 ;; esac
eta=$((10#$eta))

# A pipe is refused unless --wait was given — on EITHER stream. The detached
# worker's subshell inherits this process's stdout AND stderr and lives as long
# as the worker, so a caller reading either through a pipe stays blocked until
# the worker exits. On ticket 290 a `| grep -v … | tail` held the call for its
# 180-second limit, and stopping it killed the worker; redirecting stdout to a
# file while stderr still went to a pipe would block exactly the same way. A
# pipe is fine with --wait, which returns when the worker does.
#
# FIFO only is not enough: an agent harness (Claude Code's Bash tool, Pi itself)
# gives its children AF_UNIX socketpairs as stdio, which fail `-p` and pass
# `-S` — and the harness waits for EOF on the socket just as it would on a pipe.
# A tty is `-c` and a redirect is `-f`, so neither is refused. Both tests follow
# /dev/stdout and /dev/stderr to the real descriptor.
if [ "$do_wait" = 0 ] && { [ -p /dev/stdout ] || [ -S /dev/stdout ] \
                        || [ -p /dev/stderr ] || [ -S /dev/stderr ]; }; then
  {
    echo "dispatch.sh: refusing — stdout or stderr is a pipe and --wait was not given."
    echo "  The worker's subshell holds both streams open until the worker exits, so a pipe"
    echo "  caller blocks on it — and killing the caller kills the worker. Two ways out:"
    echo "    redirect to files:  dispatch.sh ... > /tmp/dispatch.out 2>&1"
    echo "    or wait for it:     dispatch.sh ... --wait"
  } >&2
  exit 2
fi

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
#
# The provider's hosts bypass the proxy first (ticket 321). A NAMED list, not
# "the provider's host": a provider outside China needs the proxy. Appended to
# NO_PROXY and no_proxy and exported, so the preflight curl below and the worker
# launched further down both go direct; a caller's own entries are kept, the
# list only adds. This is what a caller's window cannot be trusted to supply —
# VS Code hands each window the environment it captured at launch, which is why
# build 2 typed the prefix by hand nine times. DISPATCH_BYPASS_HOSTS replaces the
# list (comma-separated, as NO_PROXY); set it empty to add nothing.
bypass_hosts="${DISPATCH_BYPASS_HOSTS-deepseek.com,.deepseek.com,api.deepseek.com}"
if [ -n "$bypass_hosts" ]; then
  # Keep the caller's entries on BOTH variables: a window that exports only one
  # (VS Code, a harness) must not lose its other bypasses here. clip/Node/Python
  # read lowercase `no_proxy` first and Go reads uppercase `NO_PROXY` first, so
  # whichever the caller set seeds the other before the list is appended.
  NO_PROXY="${NO_PROXY:-${no_proxy:-}}"
  no_proxy="${no_proxy:-$NO_PROXY}"
  NO_PROXY="${NO_PROXY:+${NO_PROXY},}${bypass_hosts}"
  no_proxy="${no_proxy:+${no_proxy},}${bypass_hosts}"
  export NO_PROXY no_proxy
fi
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
    # The preflight's two ways of being un-runnable are named as themselves: a
    # missing curl and a baseUrl that is not a URL string both used to read as
    # "the worker cannot reach its model's API", which is a different fault and a
    # different fix. DISPATCH_CURL is the test seam for the missing-curl case.
    curl_cmd="${DISPATCH_CURL:-curl}"
    if ! command -v "$curl_cmd" >/dev/null 2>&1; then
      {
        echo "dispatch.sh: refusing — curl is missing, and the preflight needs it before launch."
        echo "    looked for: ${curl_cmd}"
        echo "    model:      ${model}"
        echo "    url:        ${preflight_url}"
        echo "  This is not a network fault: nothing ran the request. Install curl, or pass"
        echo "  --no-preflight to launch without the check."
      } >&2
      exit 5
    fi
    case "$preflight_url" in
      http://*|https://*) ;;
      *)
        {
          echo "dispatch.sh: refusing — the model's API baseUrl is not a URL string."
          echo "    model:   ${model}"
          echo "    baseUrl: ${preflight_url}"
          echo "  Read from \$PI_CODING_AGENT_DIR/models.json, providers[\"<provider>\"].baseUrl."
          echo "  Set it to an http(s) URL, or pass --no-preflight to launch without the check."
        } >&2
        exit 5
        ;;
    esac
    preflight_rc=0
    preflight_err="$("$curl_cmd" -q -sS -o /dev/null --max-time 10 -- "$preflight_url" 2>&1)" || preflight_rc=$?
    if [ "$preflight_rc" != 0 ]; then
      {
        echo "dispatch.sh: refusing — the worker cannot reach its model's API before launch."
        echo "    model: ${model}"
        echo "    url:   ${preflight_url}"
        echo "    error: curl exit ${preflight_rc}: ${preflight_err}"
        echo "  Any HTTP status (401 counts) means reachable; no response does not."
        echo "  The bypass list this dispatch applied: ${bypass_hosts:-<none>}"
        echo "  Next check: the same request through the proxy your shell exports:"
        echo "    curl -sS -o /dev/null -m 10 '${preflight_url}'"
        echo "  If that answers and this one does not, the proxy is the way in: re-run with"
        echo "  DISPATCH_BYPASS_HOSTS= (and drop the host from your own NO_PROXY)."
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
# and the subshell publishing the pid. `record_in_flight` in lib/in-flight.sh
# holds it until its deadline (or a day from its mtime when the deadline is
# unreadable), then releases it — see that function for the full predicate.
#
# This scan is also where a record whose worker is dead and that never closed
# gets closed (task 341): `finished` written, `exit_code: -1` ("the worker was
# lost, not seen to exit"), its .pid file removed. Nothing else ever closed those,
# so one killed subshell left a record that orchestrator-count.sh reported DEAD
# forever and a .pid file beside it.
#
# Records are machine-local and gitignored (ADR 0086), so this only ever sees
# what is on this machine's disk. That is the whole scope of the rule.

# The working tree this dispatch is being launched from — NOT `root`, which is
# the shared main checkout every worktree resolves to.
this_tree="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

# One shared predicate with ticket.sh's ceiling check (task 341): the reasons,
# the deadline rule and the mtime fallback all live in lib/in-flight.sh, so the
# two callers cannot drift into counting different dispatches.
source "${script_dir}/lib/in-flight.sh"

pi_in_flight=0          # how many Pi dispatches are live right now
blocking_lane=""        # a live one already on THIS working tree, if any
blocking_record=""
blocking_pid=""
blocking_reason=""
while IFS= read -r rec; do
  [ -n "$rec" ] || continue
  if ! record_in_flight "$rec"; then
    close_lost_record "$rec" || true
    continue
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
# Two dispatches of one lane in the same second share a filename, and the second
# record used to overwrite the first — a worker that died at once and was sent
# back within the second lost the earlier record (`lands.tsv` counts records, so
# `dispatches` read one short). The second gets a `_NN` suffix: the `${lane}-*`
# glob every reader uses still matches it, and the name still starts with
# `<lane>-<ts>`. The ORDER between two records of one second is not something a
# filename can promise (glob and `sort` collate `_` against `.` by locale, and the
# opposite way in C), so a reader that needs the newer one compares the record's
# `started` first and the padded suffix second — see `send_back_reason` and
# `cmd_status` in ticket.sh.
seq_n=1
while [ -e "${dispatch_dir}/${stem}.json" ]; do
  seq_n=$((seq_n + 1))
  stem="${lane}-${ts}_$(printf '%02d' "$seq_n")"
done
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
  "reason": "$(json_escape "$reason")",
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
#
# The WHOLE wait also has an upper bound (task 342): the record's own deadline
# plus WAIT_GRACE. ask-pi has no timeout, so a worker that wedges would otherwise
# hold the waiter (and caffeinate) for ever. The deadline is READ FROM THE RECORD
# — the same field a poller reads — with this run's in-process deadline as the
# fallback when it is missing or unreadable. Stopping the wait does not stop the
# worker: it is disowned, and the record stays its handle. 300 s covers a worker
# that answers at its deadline and then writes its closing record; a longer grace
# would let a wedged worker hold a caller for hours at a long --eta.
WAIT_GRACE="${DISPATCH_WAIT_GRACE:-300}"
case "$WAIT_GRACE" in ''|*[!0-9]*) WAIT_GRACE=300 ;; esac
if [ "$do_wait" = 1 ]; then
  # Read the deadline into a variable first: an empty or null one must never reach
  # epoch_from_iso, because GNU `date -d ""` means TODAY'S 00:00 (Linux) and the
  # bound would land in the past, exiting 6 at once. lib/in-flight.sh avoids the
  # same trap the same way. This run's own deadline is the fallback.
  wait_dl="$(record_field "$record_path" deadline || true)"
  wait_bound=""
  if [ -n "$wait_dl" ] && [ "$wait_dl" != null ]; then
    wait_bound="$(epoch_from_iso "$wait_dl")"
  fi
  case "$wait_bound" in ''|*[!0-9]*) wait_bound="$deadline_epoch" ;; esac
  wait_bound=$((wait_bound + WAIT_GRACE))
  gone_polls=0
  empty_pid_polls=0
  while :; do
    # The closed record is read BEFORE the bound: a worker that closed between
    # two polls must get its own exit code, not "unknown fate" because 300 s
    # happened to end in the same 0.2 s.
    wait_finished="$(record_field "$record_path" finished || true)"
    if [ -n "$wait_finished" ] && [ "$wait_finished" != null ]; then break; fi
    if [ "$(date -u +%s)" -ge "$wait_bound" ]; then
      echo "dispatch.sh: --wait stopped ${WAIT_GRACE}s after the record's deadline; worker ${worker_pid:-?} may still be running — poll the record: ${record_path}" >&2
      tail -n 20 "$log_path"
      exit 6
    fi
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
  # -1 is the closer's mark (lib/in-flight.sh) for a record some other run closed
  # as lost. That is the unknown fate exit 6 names, not a worker code 255.
  if [ "$wait_rc" = -1 ]; then
    echo "dispatch.sh: the record was closed as lost (exit_code -1); the worker's fate is unknown — see ${log_path}" >&2
    tail -n 20 "$log_path"
    exit 6
  fi
  if [ -z "$wait_rc" ] || [ "$wait_rc" = null ]; then
    echo "dispatch.sh: the record closed with no exit_code; the worker's fate is unknown — see ${log_path}" >&2
    tail -n 20 "$log_path"
    exit 6
  fi
  tail -n 20 "$log_path"
  exit "$wait_rc"
fi
