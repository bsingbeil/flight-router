#!/usr/bin/env bash
# in-flight.sh — the one "is this dispatch record in flight?" predicate (task
# 341), shared by `dispatch.sh` (both ADR 0086 gates) and `ticket.sh start` (the
# ceiling check before it makes a branch, lane or worktree). One predicate means
# the two can never disagree about who holds the ceiling — ticket 322's `workers`
# and ticket 329's `lane prune` read the same function.
#
# Source this file; it is not meant to be executed directly. It needs
# `epoch_from_iso` from lib/portable-date.sh, so source that first.
#
# A record's fields are read with record_field, below: our writer emits one
# "key": value per line and an unclosed `finished` is the literal `null`.

# record_field <record file> <key> — the record's value for <key>, quotes and a
# trailing comma stripped. One key per line, so a targeted sed needs no jq.
record_field() {
  sed -n "s/^[[:space:]]*\"$2\":[[:space:]]*//p" "$1" | head -1 \
    | sed -e 's/^"//' -e 's/",\{0,1\}[[:space:]]*$//' -e 's/,[[:space:]]*$//'
}

# file_mtime <file> -> epoch seconds, empty if unavailable.
# GNU first: BSD `stat -c` fails cleanly with no stdout, but GNU `stat -f %m`
# reads -f as --file-system and prints a filesystem block, so the old order put
# junk in $bound on Linux and the arithmetic below would abort.
file_mtime() {
  stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null || true
}

# A record is in flight when it has no `finished` AND its worker is not provably
# gone. A live pid is the proof. A record written before the pid was known (the
# parent writes the pid a moment later, and a crash in that window leaves it
# null) is held only until its own `deadline`, or a day past its mtime when the
# deadline is missing or unreadable: either way a pid-less open record stops
# holding the gate, because past that it can never prove it is alive.
#
# Returns 0 in flight, 1 not. Sets rif_pid (the effective pid, empty when the
# record has none) and rif_reason for the caller's refusal note:
#   live-pid | pidfile | young-pidless | no-deadline
record_in_flight() { # <record file>
  local rec="$1" finished pid dl dl_epoch pf bound now_epoch
  rif_pid=""; rif_reason=""
  now_epoch="$(date -u +%s)"
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
  # note says so, rather than claiming a deadline it could not read.
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

# close_lost_record <record file> — close a record that never closed, when its
# worker is provably gone: write `finished` and `exit_code: -1` (the worker was
# lost, not seen to exit), remove the sibling .pid file, say so on stderr and add
# one line to the record's log. Returns 0 when it closed the record; 1 when there
# was nothing to close — the record already closed, its worker may still be alive
# (a live pid, or no pid at all: nothing proves that one gone), or the record is
# too new to be sure its own subshell is not still closing it (below).
#
# The write is a temp file renamed into place, and open is re-read just before
# the rename: the launching subshell may have written its closing record while
# this ran, and a closed record is never overwritten with a guess.

# A record last written less than this many seconds ago may still be being
# closed by its own launching subshell: after `wait` reaps the worker that
# subshell still has a few forks to run (date, the temp write) before its rename
# lands. A closer that moved first would overwrite the real exit code with -1 and
# add a false "lost" line to the log, so a record has to be older than this
# before it is treated as lost. A genuinely lost record is minutes to days old.
LOST_RECORD_GRACE=60

close_lost_record() {
  local rec="$1" finished pid pf again log tmp ts mtime age closed_at
  finished="$(record_field "$rec" finished)"
  [ -z "$finished" ] || [ "$finished" = null ] || return 1
  pid="$(record_field "$rec" pid)"
  pf="$(dirname "$rec")/.$(basename "$rec" .json).pid"
  # The same .pid fallback record_in_flight uses: a crash between the pid-file
  # write and the record's pid write leaves `pid: null` with the worker's pid in
  # the sibling file, and this record must still be closable.
  if [ -z "$pid" ] || [ "$pid" = null ]; then
    if [ -s "$pf" ]; then pid="$(cat "$pf" 2>/dev/null || true)"; fi
  fi
  [ -n "$pid" ] && [ "$pid" != null ] || return 1
  kill -0 "$pid" 2>/dev/null && return 1
  mtime="$(file_mtime "$rec")"
  case "$mtime" in ''|*[!0-9]*) return 1 ;; esac
  age=$(( $(date -u +%s) - mtime ))
  [ "$age" -ge "$LOST_RECORD_GRACE" ] || return 1
  ts="$(iso_from_epoch "$(date -u +%s)")"
  tmp="${rec}.lost.$$"
  sed -e "s/^\([[:space:]]*\"finished\":[[:space:]]*\)null.*/\1\"${ts}\",/" \
      -e 's/^\([[:space:]]*"exit_code":[[:space:]]*\)null.*/\1-1/' \
      "$rec" > "$tmp" 2>/dev/null || { rm -f "$tmp"; return 1; }
  # The sed has to have closed it: a `finished` key in a shape it does not match
  # would leave the record open, and every side effect below would then lie
  # (and repeat on every later run).
  closed_at="$(record_field "$tmp" finished)"
  if [ -z "$closed_at" ] || [ "$closed_at" = null ] || [ "$(record_field "$tmp" exit_code)" != -1 ]; then
    rm -f "$tmp"; return 1
  fi
  again="$(record_field "$rec" finished)"
  if [ -n "$again" ] && [ "$again" != null ]; then rm -f "$tmp"; return 1; fi
  mv -f "$tmp" "$rec" || { rm -f "$tmp"; return 1; }
  rm -f "$pf"
  log="$(record_field "$rec" output_path)"
  if [ -n "$log" ] && [ "$log" != null ] && [ -f "$log" ]; then
    printf 'dispatch.sh: worker %s was gone and its record never closed; the next run closed it as lost (exit_code -1) at %s\n' \
      "$pid" "$ts" >> "$log" 2>/dev/null || true
  fi
  echo "dispatch.sh: closed a lost dispatch record: ${rec} (worker ${pid} is gone, never closed; exit_code -1)" >&2
  return 0
}
