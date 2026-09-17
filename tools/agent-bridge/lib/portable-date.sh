#!/usr/bin/env bash
# portable-date.sh — BSD (macOS) / GNU `date` compatibility helpers, shared
# by dispatch.sh and orchestrator-count.sh. Source this file; it is not
# meant to be executed directly.

# iso_from_epoch <epoch-seconds>
#   Prints an ISO-8601 UTC timestamp for the given epoch, e.g.
#   2026-09-14T09:00:00Z. Tries BSD `date` (macOS) first, then GNU `date`.
iso_from_epoch() {
  date -u -r "$1" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null \
    || date -u -d "@${1}" +%Y-%m-%dT%H:%M:%SZ
}

# epoch_from_iso <iso-8601-utc-timestamp>
#   Prints the epoch seconds for an ISO-8601 UTC timestamp like
#   2026-09-14T09:00:00Z. Prints nothing (not an error) if unparseable —
#   callers are expected to check for an empty result.
epoch_from_iso() {
  date -u -j -f '%Y-%m-%dT%H:%M:%SZ' "$1" +%s 2>/dev/null \
    || date -u -d "$1" +%s 2>/dev/null \
    || true
}
