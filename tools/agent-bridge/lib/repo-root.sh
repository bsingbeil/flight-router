#!/usr/bin/env bash
# repo-root.sh — resolve the shared main-checkout root for agent-bridge
# scripts, regardless of which worktree (or plain checkout) they are running
# from. Source this file; it is not meant to be executed directly.
#
# `git rev-parse --show-toplevel` resolves to the CALLING worktree's own
# root, which differs per worktree. `git rev-parse --git-common-dir` returns
# the SAME .git directory from every worktree of a repo — it's what `lane`
# already uses for `lanes.tsv` so every window sees one registry. Dispatch
# records need the same property: dispatch.sh (run from inside a worktree,
# per ADR 0086's --worktree-mandatory rule) and orchestrator-count.sh (run
# from the main checkout, under launchd) must agree on one directory or the
# watcher can never see a compliant dispatch.
#
# agent_bridge_root [<git-context-dir>]
#   Prints the absolute path to the main checkout's root (the parent of its
#   .git directory) — NOT inside .git/ itself; ADR 0086 explicitly rejects
#   that, since it's where lanes.tsv rotted to 24 stale rows unnoticed.
#   <git-context-dir> defaults to the current directory; pass the caller's
#   script_dir when the caller may run with an unrelated cwd (e.g. launchd).
#   Falls back to that context dir, absolutized, if it isn't inside a git
#   repo at all.
agent_bridge_root() {
  local ctx="${1:-.}" common
  common="$(git -C "$ctx" rev-parse --git-common-dir 2>/dev/null)" || {
    (cd "$ctx" && pwd)
    return
  }
  case "$common" in
    /*) : ;;
    *) common="${ctx}/${common}" ;;
  esac
  common="$(cd "$common" && pwd)"
  dirname "$common"
}
