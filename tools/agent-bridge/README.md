# agent-bridge

Commands and gates that let Claude Code and Pi work together without Brendan
relaying messages between them.

| Command | Does |
|---|---|
| `ask-pi "<msg>"` | Claude Code → Pi. Pi's reply prints on stdout, straight into the caller's context. |
| `ask-claude "<msg>"` | Pi → Claude Code. Claude answers with read-only tools — it reviews, Pi edits. |
| `lane new <name> --owns <path>` · `lane who [path]` | Claims a session id + owned paths (optionally its own worktree) and prints a paste-ready coordinates block for a second terminal window. **Refuses a tree another live Claude session holds** (task 107, see below); `lane who` shows who is in a tree. |
| `dispatch.sh --lane <name> --task <id> [--series <s>] [--eta <min>] [--force] [--force-shared-checkout] "<msg>"` | Backgrounds an `ask-pi` call and leaves a JSON status record under `.claude/dispatch/` for polling instead of blocking. **Enforces ADR 0086's two concurrency rules before it launches anything** — see below. |
| `orchestrator-count.sh [--quiet]` | The only scheduled counter: counts unfiled done-tasks, overdue dispatch records, stale PRs, and (task 079) any loaded `com.navigate*`/`com.navigateops.*` launchd job sitting at a non-zero, non-`-` exit status. Own exit codes: `0` nothing crossed, `2` something crossed AND every escalation of it landed in `PENDING/`, `1` a crossing's escalation FAILED to land (or the script couldn't establish its own bearings), `64` bad usage — `2` is reserved for "found something and told someone", never conflated with a real failure. Run under `run-job.sh`, which maps that `2` to a clean launchd status; see its header for the full contract. |
| `<report-lines> \| escalate-crossing.sh <kind>` | The "tell someone" half of the counter: turns a crossing into one file per finding kind in `workspaces/coo/decisions/PENDING/`, landed on `main` through a throwaway worktree. Re-runs update that file rather than piling up duplicates. Called by `orchestrator-count.sh`, not by hand. |
| `ask-rawls --ask <task-slug>:<blocker-slug> "<question>" [--live]` | Dispatcher → Rawls. One fresh Fable call per ask on the Claude plan, capped at $6 per call (two calls per key, so $12 per question), fanned out in parallel, reading only a snapshot of `main`'s record. A cited ruling lands in `workspaces/rawls/ANSWERS.md` on `main`; an uncited question comes back as residue (`--live`) or goes to `PENDING/`. Two calls per issue key, then a human. **Refuses executors** (Pi sessions, bridge chains) and is deliberately **not** linked into `~/bin`. Procedure: `.claude/skills/dispatcher-blocked/`. |
| `check-task-filed.sh [--range <git-range>] [--count]` | Pre-merge gate — fails if a `tasks/inbox/*.md` file is `status: done` but hasn't been moved to `tasks/done/`. `--count` prints a bare count (then offending paths) for `orchestrator-count.sh` to consume, instead of parsing prose. |
| `health-check.sh [--update-baseline]` | The weekly health check (task 079), rebuilt model-free: deno lint/check/test over `supabase/functions`, Supabase advisors diffed against a committed baseline (`health-baseline.txt`), and a pipeline snapshot (shipment legs, alerts, unacked notifications, the two tracking cron jobs). Writes a dated report to `HEALTH_REPORT_DIR` (default `~/Library/Logs/navigate-ops/health/`, never committed). Own exit codes: `0` clean/watch, `2` a real RED AND the PENDING escalation landed, `1` a check could not run at all OR a RED's PENDING write failed (could-not-report is the same bucket as could-not-run — that distinction is the whole point of task 079), `64` bad usage. A RED lands one `workspaces/coo/decisions/PENDING/health-check.md`, same dedupe shape as the counter's crossings. Run under `run-job.sh`, which maps `2` to a clean launchd status. |
| `launchd/run-job.sh <repo-relative-script> [args...]` | What every `com.navigate*` launchd job actually invokes (task 036). Refreshes the dedicated jobs checkout (`~/Sites/navigate-ops-jobs`, gitignored from this repo, a `git worktree` detached at `origin/main`) to `origin/main`, refuses to run against it if it's missing or dirty, then runs the named script relative to it (not `exec` — it stays alive to translate the exit code). **The exit-code contract**, so `launchctl list`'s status column can't conflate "found something and reported it" with a crash: target exit `0` → `0`; target exit `2` (ran, found something, reported it successfully) → `0`, logged as `findings reported (rc 2)`; anything else (could not run, or ran but could not report) → passed through unchanged, which is what `failing-launchd-jobs` (arm 5 of `orchestrator-count.sh`) watches for. Never run by hand outside a test — see `launchd/INSTALL.md`. |

`dispatch.sh`, `orchestrator-count.sh`, `escalate-crossing.sh`, and
`check-task-filed.sh` carry a `.sh` extension and are invoked by path, unlike `ask-pi` / `ask-claude` / `lane` /
`sync` above, which are extensionless commands symlinked into `~/bin`. That's
the whole distinction — the `.sh` scripts are in-repo gates and helpers, not
standalone commands, so they were never symlinked out. **`ask-rawls` is the one
exception**: extensionless like a command, but deliberately *not* symlinked into
`~/bin` — putting Rawls on every agent's command path would widen the reach its
executor refusal exists to narrow, so the Dispatcher runs it by its repo path.
`lib/frontmatter.sh`, `lib/portable-date.sh`, and `lib/repo-root.sh` are shared
helpers sourced by the `.sh` scripts (and, for `repo-root.sh`, by `dispatch.sh`
too — it resolves the one shared main-checkout directory regardless of which
worktree a script runs from, the same way `lane` resolves `lanes.tsv`'s
location). `lib/land-on-main.sh` is the one write path to `main`'s tree — the
throwaway-worktree drain `escalate-crossing.sh` and `ask-rawls` both use, so it
exists once. `lib/pending-writer.sh` (task 121) is the one PENDING-file writer (`write_one` +
`pending_frontmatter`: one open file per kind, a re-run keeps `created:` and bumps `last-seen:`),
shared by `escalate-crossing.sh` and `health-check.sh` so their dedupe rule cannot drift apart.
None of them are meant to be run directly. Tests for `ask-rawls`
live in `tests/ask-rawls.test.sh` (stubbed `claude`, fake origin, no model calls).

Both `ask-*` commands accept piped stdin (`git diff | ask-pi "review this"`),
take `-t <thread>` for parallel conversations, and are threaded per git repo
root so no context bleeds between projects. A depth guard stops the two agents
ping-ponging past 2 hops.

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

## What `dispatch.sh` refuses, and why

ADR 0086 sets two rules for parallel dispatch. `dispatch.sh` now checks both
**before** it writes a record or launches `ask-pi`, so a refusal leaves nothing
behind. Both read the same `.claude/dispatch/*.json` records the script already
writes; a record counts as in flight only if `finished` is still `null` **and**
its pid is still alive, so one crashed worker can't hold the gate shut.

| Exit | Refusal | Override |
|------|---------|----------|
| `3` | Another unfinished Pi dispatch is already running against **this same working tree**. A git worktree is mandatory for every parallel Pi lane — two unattended `--approve` agents on one checkout is a data-loss bug waiting for a slow afternoon. | `--force-shared-checkout` |
| `4` | The **2-Pi ceiling** is already reached. Counts `worker: "pi"` only, and says so: `dispatch.sh` is the only thing that writes records today, so the Sonnet half of "2 Pi + 2 Sonnet" is unenforceable rather than silently enforced. | `--force`, or `DISPATCH_PI_CEILING=<n>` for a session |

**The two overrides are deliberately separate flags.** The ceiling is a
calibration guess (ADR 0086; task 031 sets the real number), so `--force` is a
reasonable thing to reach for. The worktree rule protects against losing work,
so `--force` must not silently switch it off as a side effect of raising the
ceiling. Each prints a loud warning naming the rule it bypassed.

Records gained a `worktree` field for this. A record written before that
(no field) blocks the shared-checkout check rather than passing it — it cannot
prove it is running somewhere else, and the conservative reading is the safe one
for the rule whose failure mode is two agents writing one checkout.

Covered by `tests/dispatch.test.sh` (stubbed `ask-pi`, real git worktrees, no Pi
call).

## What `lane` refuses, and why — one writer per tree (task 107)

The Claude-side twin of `dispatch.sh`'s exit 3 above. **`lane new` refuses (exit 3) to claim a
directory held by ANOTHER live Claude session.** A tree is "held" when (a) another live Claude
session's `cwd` resolves to that tree, or (b) an existing lane records that `dir` and its
`claimed_by` session is still live. Live-session source: `~/.claude/sessions/*.json` (`pid`,
`sessionId`, `cwd`, `name`, `status`); a session is live if its `pid` is. CEO decision 2026-09-24:

| Access | Rule | Override |
|---|---|---|
| Read-only co-tenancy | Allowed, as long as both sessions know. `lane who [path]` lists every live session and every lane in a tree (read-only, exit 0). | — |
| Claiming the tree to write | Refused (exit 3), naming the holder. | `--share-worktree` — its own named flag, not `--force`. Prints a loud warning naming the rule bypassed and tells you to `SendMessage` the holder. |

- `lane ls` resolves each lane's holder at print time: `SESSION` is the claiming session's name +
  short id, `STATE` is `live | STALE | unknown`. `unknown` means the claimant's liveness is not
  observable here: no `claimed_by`, or a Pi claimant, whose session id never appears in Claude's
  session files. Nothing is auto-removed.
- `lane new` detects a linked worktree from `--git-common-dir` vs `--git-dir`, whatever flags were
  passed, and attributes the agent from the environment (`claude` if `CLAUDE_CODE_SESSION_ID`,
  else `pi` if `PI_SESSION_ID`, else `--agent` is required). A claude lane's "reach it" line is
  `SendMessage to "<name>"`, never `ask-pi`.
- **Sessions are filed by working directory, and it follows `EnterWorktree`.** A session that moved
  into a worktree is recorded under that worktree, not the main checkout, so `lane who` on the main
  checkout will not list it. They are separate trees with separate writers, which is correct.
- **The limit.** This guards the CLAIM (`lane new`), not every file write: a session that starts
  editing without claiming is not stopped, only visible to `lane who`. The per-write guard and the
  push notice to the holding session are task 154. Tests: `tests/lane.test.sh` (stubbed session
  files, real linked worktree, nothing real touched).

## What `lane` refuses, and why — one review per PR (task 109)

A review claims its PR, not a path: `lane review <pr>` = `lane new review/<pr> --owns pr/<pr>` — a
lane keyed to a number instead of a directory, because a review edits nothing. `lane new` REFUSES
(exit 3) a second claim of `pr/<n>` while another lane already owns it — **reviews are 1:1 with a
PR, never concurrent** (CEO decision 2026-09-24). The refusal names the live holder; if the holder
is gone (or its liveness is unknown), it says to cancel the claim explicitly with
`lane rm review/<n>` first. There is **no override flag**, and nothing is auto-removed: a dead or
unobservable claimant still holds the claim until it is cancelled. A review claim holds a PR,
not a tree: it neither needs nor triggers the one-writer-per-tree gate above, so a reviewer can claim
from any tree, and its claim never blocks someone else's write claim there.

`lane reviews <pr>` is the pre-merge check: it lists every claim of `pr/<n>` with its
`live | STALE | unknown` state (same resolution as `lane ls`) and exits 0 if none is open, 1 if
any claim exists. Run it before merging — a PR does not merge on the first GREEN, every review
must report. **A review is outstanding until it reports, or until its claim is explicitly
cancelled** (`lane rm review/<n>`); a session that went away still counts as outstanding until the
claim is removed.

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

`orchestrator-count.sh`, `check-task-filed.sh`, `health-check.sh`,
`health-baseline.txt`, and `launchd/` are deliberately **not** mirrored. All of
them hardcode this repo's layout — `tasks/inbox/` + `tasks/done/`, this
project's Supabase project ref and edge functions, its PR conventions, the
literal path `/Users/bsingbeil/Sites/navigate-ops-jobs` — so copied into
another repo they would count *that* repo's unrelated files and report
nonsense instead of failing loudly. If a target repo needs the same watcher or
health check, write it its own copy against its own layout rather than syncing
this one in.

## The jobs checkout

Every scheduled `com.navigate*`/`com.navigateops.*` launchd job runs through
`launchd/run-job.sh`, from `/Users/bsingbeil/Sites/navigate-ops-jobs` — a
dedicated `git worktree`, detached at `origin/main`, that nobody works in
(task 036). It is **not** the shared `~/Sites/navigate-ops` checkout, which is
disciplined to stay on whatever branch a session last left it on and has no
guarantee of being on `main` when a job fires. `run-job.sh` refreshes it to
`origin/main` before every run and refuses outright if it's missing or dirty.
Setup and verification: `launchd/INSTALL.md`.

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

`health-check.sh` additionally wants `deno`, `psql`, `curl`, `jq`, and (for the
keychain fallback) macOS `security` — each missing tool degrades its own check
to a `note` (deno) or `COULD NOT RUN` (the rest) rather than failing the whole
script. `orchestrator-count.sh`'s `failing-launchd-jobs` arm wants `launchctl`
(`LAUNCHCTL_BIN` override for tests); missing it is a `SKIPPED` note, same
pattern as `gh` for the stale-PRs arm.
