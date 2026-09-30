#!/usr/bin/env bash
# lib/lane-core.sh — session and lane-registry primitives shared by `lane`
# and `lane-guard` (task 154, "shared core, not a copy"). Source this file;
# it is not meant to be executed directly.
#
# Callers are expected to set (before calling functions that need them):
#   sessions_dir  — where session JSON files live. `lane` and `lane-guard`
#                   both default it to ${LANE_SESSIONS_DIR:-$HOME/.claude/sessions}.
#   REG           — the lanes.tsv registry path (see lane_registry_path/
#                   lane_common_dir below) for reg_rows().
#
# Nothing in here writes to $REG — only `lane`'s own commands (lane new,
# lane rm) do that. lane_notify_holder is the one function here that writes
# anything, and it writes to the lane-notices/ directory, never the registry.

# canon <path> — canonical absolute path (symlinks resolved), so /private/tmp
# vs /tmp or any symlink cannot make two paths for one tree look different.
# When <path> does not exist yet (a new file under a brand-new subdir), walks
# up to its nearest existing ancestor and resolves THAT — the way git itself
# resolves a not-yet-created path — so the caller's `git -C` still lands inside
# the real tree instead of failing and reading as "not in a work tree".
canon() {
  local p="$1" q
  p="$(cd -P "$1" 2>/dev/null && pwd -P)" && { printf '%s' "$p"; return; }
  q="$1"
  while [ -n "$q" ] && [ ! -d "$q" ]; do q="$(dirname "$q")"; done
  p="$(cd -P "$q" 2>/dev/null && pwd -P)" && { printf '%s' "$p"; return; }
  printf '%s' "$1"
}

# tree_of <path> — canonical `git rev-parse --show-toplevel` of <path>; empty
# when <path> is not inside a git work tree. Never fails (set -e safe).
tree_of() {
  local d t
  d="$(canon "$1")"
  t="$(git -C "$d" rev-parse --show-toplevel 2>/dev/null)" || t=""
  [ -n "$t" ] || return 0
  canon "$t"
}

is_live() { kill -0 "$1" 2>/dev/null; }

# lane_common_dir — canonical absolute path of `git rev-parse --git-common-dir`
# for the repo containing the current directory. Every worktree of one repo
# resolves to the same path, which is why `lane`'s registry and lane-guard's
# holder lookup agree on where lanes.tsv lives regardless of which worktree
# either runs from. Fails (nonzero, no output) when not inside a git repo —
# callers that must not die on that (lane-guard) capture it accordingly.
lane_common_dir() { cd "$(git rev-parse --git-common-dir)" 2>/dev/null && pwd; }

# lane_notices_dir — the lane-notices directory: LANE_NOTICES_DIR if set
# (tests, smoke runs), else <lane_common_dir>/lane-notices. Fails (nonzero,
# no output) when neither resolves (not in a git repo and no override).
lane_notices_dir() {
  local common
  if [ -n "${LANE_NOTICES_DIR:-}" ]; then
    printf '%s' "$LANE_NOTICES_DIR"
    return 0
  fi
  common="$(lane_common_dir 2>/dev/null)" || return 1
  printf '%s/lane-notices' "$common"
}

# lane_registry_path — <lane_common_dir>/lanes.tsv, creating the header row
# if the file doesn't exist yet. Prints the path. `lane` calls this to get
# $REG; lane-guard calls it read-only (the header-create is idempotent and
# harmless either way).
lane_registry_path() {
  local common reg
  common="$(lane_common_dir)" || return 1
  reg="${common}/lanes.tsv"
  [ -f "$reg" ] || printf 'name\tagent\tsession\tdir\tbranch\towns\tcreated\tclaimed_by\n' > "$reg"
  printf '%s' "$reg"
}

# reg_rows — every lanes.tsv row after the header, from $REG. Empty (not an
# error) if $REG is unset, missing, or unreadable.
reg_rows() { tail -n +2 "${REG:-/dev/null}" 2>/dev/null; }

short_id() { printf '%.8s' "$1"; }

# session_fields <file> — pid\tsessionId\tcwd\tname\tstatus; empty if unparseable.
# Frozen shape: `lane` destructures this into exactly 5 fields in several
# places, so a 6th column here would silently shift every one of them.
session_fields() { jq -r '[.pid//"",.sessionId//"",.cwd//"",.name//"",.status//""]|@tsv' "$1" 2>/dev/null || true; }

# session_started_at <file> — a session's `startedAt` (epoch milliseconds),
# or empty if absent/unparseable. A sibling to session_fields, added for
# task 154's earliest-started tiebreak: `lane` never reads this field, so
# session_fields' shape (and every caller that destructures it) stays frozen.
session_started_at() { jq -r '.startedAt // empty' "$1" 2>/dev/null || true; }

# session_by_id <sessionId> — the one session file whose .sessionId matches, as
# pid\tsessionId\tcwd\tname\tstatus; empty if none. Never fails.
session_by_id() {
  local want="$1" f pid sid cwd name status
  for f in "$sessions_dir"/*.json; do
    [ -f "$f" ] || continue
    IFS=$'\t' read -r pid sid cwd name status <<< "$(session_fields "$f")"
    [ -n "$sid" ] || continue
    [ "$sid" = "$want" ] || continue
    printf '%s\t%s\t%s\t%s\t%s\n' "$pid" "$sid" "$cwd" "$name" "$status"
    return 0
  done
  return 0
}

# review_only <owns> — true when every owned path is a pr/<n> pseudo-path, i.e.
# the lane claims a PR review and edits no tree. Such a lane neither needs the
# one-writer-per-tree gate nor counts as holding the tree it was claimed from.
review_only() {
  local o="$1" a
  [ -n "$o" ] || return 1
  for a in ${o//,/ }; do
    case "$a" in pr/*) : ;; *) return 1 ;; esac
  done
  return 0
}

# lane_notify_holder <holder-session-id> <verb> <cotenant-name> <cotenant-short-id> <tree>
#   Appends one line to <notices-dir>/<holder-session-id> — the holder's
#   queue, delivered by `lane-guard notices` on its next prompt or tool call
#   (task 154, design note 3). <verb> is "tried to write in" (a refusal) or
#   "is sharing" (a --share-worktree bypass).
#
#   Deduped on (holder, cotenant, tree) via <notices-dir>/<holder>.seen, so
#   the holder hears about one co-tenant/tree pairing once, not on every
#   write attempt. The dedupe record is never cleared by delivery — only a
#   NEW (cotenant, tree) pairing writes again.
#
#   <notices-dir> defaults to <lane_common_dir>/lane-notices; LANE_NOTICES_DIR
#   overrides it (tests, and the manual smoke test, so nothing real is
#   written to a live holder while proving the refusal path).
#
#   Fails open silently: a notice that can't be written must never block the
#   caller's own decision (a refusal, or a --share-worktree bypass) — this
#   function's return value is not meant to be checked.
lane_notify_holder() {
  local holder="$1" verb="$2" cname="$3" cshort="$4" tree="$5"
  [ -n "$holder" ] || return 0
  local dir
  dir="$(lane_notices_dir 2>/dev/null)" || return 0
  mkdir -p "$dir" 2>/dev/null || return 0
  local seen="${dir}/${holder}.seen" key
  key="$(printf '%s\t%s' "$cshort" "$tree")"
  touch "$seen" 2>/dev/null || return 0
  grep -qF "$key" "$seen" 2>/dev/null && return 0
  local now
  now="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null)" || now=""
  # `|| return 0` on both appends: this function is sourced by `lane`, which
  # runs under `set -e`. A notice write that fails (unwritable dir) must
  # never kill the caller's own decision — fail open silently.
  printf '%s [%s] %s %s at %s\n' "$cname" "$cshort" "$verb" "$tree" "$now" >> "${dir}/${holder}" 2>/dev/null || return 0
  printf '%s\n' "$key" >> "$seen" 2>/dev/null || return 0
  return 0
}
