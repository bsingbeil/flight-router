# agent-bridge

Commands and gates that let Claude Code and Pi work together without Brendan
relaying messages between them.

| Command | Does |
|---|---|
| `ask-pi "<msg>"` | Claude Code → Pi. Pi's reply prints on stdout, straight into the caller's context. |
| `ask-claude "<msg>"` | Pi → Claude Code. Claude answers with read-only tools — it reviews, Pi edits. |
| `lane new <name> --owns <path>` | Claims a session id + owned paths (optionally its own worktree) and prints a paste-ready coordinates block for a second terminal window. |
| `dispatch.sh --lane <name> --task <id> [--series <s>] [--eta <min>] "<msg>"` | Backgrounds an `ask-pi` call and leaves a JSON status record under `.claude/dispatch/` for polling instead of blocking. |
| `orchestrator-count.sh [--quiet]` | The only scheduled job: counts unfiled done-tasks, overdue dispatch records, and stale PRs; exits non-zero only when a threshold crosses, so a model call is a deliberate escalation, not a standing cost. |
| `<report-lines> \| escalate-crossing.sh <kind>` | The "tell someone" half of the counter: turns a crossing into one file per finding kind in `workspaces/coo/decisions/PENDING/`, landed on `main` through a throwaway worktree. Re-runs update that file rather than piling up duplicates. Called by `orchestrator-count.sh`, not by hand. |
| `check-task-filed.sh [--range <git-range>] [--count]` | Pre-merge gate — fails if a `tasks/inbox/*.md` file is `status: done` but hasn't been moved to `tasks/done/`. `--count` prints a bare count (then offending paths) for `orchestrator-count.sh` to consume, instead of parsing prose. |

`dispatch.sh`, `orchestrator-count.sh`, `escalate-crossing.sh`, and
`check-task-filed.sh` carry a `.sh` extension and are invoked by path, unlike `ask-pi` / `ask-claude` / `lane` /
`sync` above, which are extensionless commands symlinked into `~/bin`. That's
the whole distinction — the `.sh` scripts are in-repo gates and helpers, not
standalone commands, so they were never symlinked out. `lib/frontmatter.sh`,
`lib/portable-date.sh`, and `lib/repo-root.sh` are shared helpers sourced by
the `.sh` scripts (and, for `repo-root.sh`, by `dispatch.sh` too — it
resolves the one shared main-checkout directory regardless of which
worktree a script runs from, the same way `lane` resolves `lanes.tsv`'s
location); none of them are meant to be run directly.

Both `ask-*` commands accept piped stdin (`git diff | ask-pi "review this"`),
take `-t <thread>` for parallel conversations, and are threaded per git repo
root so no context bleeds between projects. A depth guard stops the two agents
ping-ponging past 2 hops.

**`ask-pi` cannot hang the caller.** Pi reads stdin to EOF whenever it isn't a
TTY, and agent harnesses hand it a pipe that never closes, so `ask-pi` runs Pi
with `</dev/null`. That one bug caused hours-long silent stalls. Pi runs with
`--mode json` under a watchdog:

| Exit | Meaning |
|---|---|
| `0` | Reply printed. Also used when Pi finished but didn't exit on its own. |
| `124` | Stalled (no events and no CPU for `PI_BRIDGE_IDLE_SECS`, default 600) or hit the `PI_BRIDGE_MAX_SECS` cap (default 7200). stderr prints a resume command for the same thread. |
| `1` | Provider error (message on stderr). |

Event logs (token deltas stripped) are written to
`~/.pi/agent/bridge-logs/<session>.jsonl`. Writeup:
`infrastructure/docs/troubleshooting/pi-bridge-stdin-hang.md`. Don't edit
`ask-pi` in place while a run is in flight: bash resumes the old process at its
old byte offset in the new file.

**The default thread is this session's lane, not a constant.** `lane new` records
the agent session that claimed it (`CLAUDE_CODE_SESSION_ID`), and `ask-*` default
to that lane's name. Without this, two Claude sessions in one worktree would both
fall back to thread `main` and interleave their conversations in a single Pi
thread — worktree keying isolates across worktrees, not within one. If the
session has claimed no lane, the default is still `main`.

A lock backs it up: one caller per thread at a time. A second concurrent caller
gets `exit 4` and is told to use `-t` or claim a lane, rather than silently
interleaving. Locks held by dead processes are reclaimed automatically.

**The thread name doubles as the lane name.** If a lane of that name is claimed,
`ask-pi -t <name>` / `ask-claude -t <name>` inject its ownership rules into the
receiving agent's instructions automatically — owned paths, other lanes' paths,
and the no-`git add -A` rule. A handoff therefore carries its own boundary
instead of depending on someone pasting it (`lane_context()`, duplicated
verbatim in both scripts — keep them in sync).

## This directory is the canonical copy

`~/bin/ask-pi`, `~/bin/ask-claude` and `~/bin/lane` are **symlinks into this
directory**. Editing a file here changes what actually runs, everywhere, with no
copy step — and the running version is always the committed version.

Eight other repos carry a mirror of these scripts so the tooling is recoverable
if this checkout is lost. Those mirrors are backups, not what executes. After
changing anything here:

```sh
tools/agent-bridge/sync      # push to every mirror, report what changed
```

then commit the mirrors in the repos it names. `sync` refuses to overwrite a
mirror that has local edits it would lose, so a diverged copy surfaces instead
of being silently clobbered.

### What `sync` mirrors, and what it doesn't

`sync` copies `ask-pi`, `ask-claude`, `lane`, `sync` itself, `dispatch.sh`, and
`lib/` — generic bridge tooling with no navigate-ops-specific assumptions
baked in, safe to run against any repo's own `tasks/`.

`orchestrator-count.sh` and `check-task-filed.sh` are deliberately **not**
mirrored. Both hardcode this repo's layout — `tasks/inbox/` + `tasks/done/`
and its PR conventions — so copied into another repo they would count *that*
repo's unrelated files and report nonsense instead of failing loudly. If a
target repo needs the same watcher, write it its own copy against its own
task layout rather than syncing this one in.

## Agent-side guidance

The scripts are only half of it — each agent also needs to know *when* to use
them. That guidance lives outside this repo, in the agents' own config:

- Claude Code: `~/.claude/CLAUDE.md` — talk to Pi directly; claim a lane before
  parallel work and paste the coordinates block verbatim.
- Pi: `~/.pi/agent/skills/ask-claude/SKILL.md` and `~/.pi/agent/skills/lane/SKILL.md`.

Repo-level usage and the lane rules are documented in [`tasks/README.md`](../../tasks/README.md).

## Requirements

`pi` and `claude` on `PATH`. Pi defaults to `deepseek-v4-pro`; the Claude side
defaults to `claude-sonnet-5` with a $0.50-per-call budget cap
(`CLAUDE_BRIDGE_MODEL`, `CLAUDE_BRIDGE_BUDGET`, `PI_BRIDGE_MODEL` override).
