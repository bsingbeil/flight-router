# agent-bridge

Commands and gates that let Claude Code and Pi work together without Brendan
relaying messages between them.

| Command | Does |
|---|---|
| `ask-pi "<msg>"` | Claude Code → Pi. Pi's reply prints on stdout, straight into the caller's context. |
| `ask-claude "<msg>"` | Pi → Claude Code. Claude answers with read-only tools — it reviews, Pi edits. |
| `lane new <name> --owns <path>` · `lane who [path]` | Claims a session id + owned paths (optionally its own worktree) and prints a paste-ready coordinates block for a second terminal window. **Refuses a tree another live Claude session holds** (task 107, see below); `lane who` shows who is in a tree. |
| `lane prune [--apply] [--all]` | Lists lanes whose session is not live and whose branch is merged into `origin/main`, whose branch is gone, or whose worktree folder is missing; a Pi lane is judged from its dispatch records (kept while a worker is in flight, otherwise listed like a `STALE` lane); `--apply` drops exactly those registry rows — never a worktree or a branch. `--all` also shows the lanes it keeps and why. See below. |
| `merge-pr.sh [--match-head <sha>] <pr>` | **The merge path (task 156).** `--match-head` (optional) pins the merge to a checked head via `gh pr merge --match-head-commit`. Runs `lane reviews <pr>` first and refuses to call `gh pr merge --merge` while any review claim on the PR is open, then prints the PR's state after the merge so the caller sees that it merged without a second call (task 343). The orchestrator and the COO merge through this, never a raw `gh pr merge`. |
| `docs-only.sh <pr>` · `docs-only.sh <base> <head>` · `docs-only.sh --paths` | Is a pull request docs-only? (task 355, implements the ADR 0085 addendum of 2026-10-19.) Exit 0 only when every entry of `git diff --no-renames --raw <base>...<head>` is an Add or Modify of a regular (mode `100644`) `.md`/`.html` file under a path the addendum lists, and — for `tasks/inbox/` — an Add only. Exit 1 names the first offending entry and why; exit 2 could not run. `--paths` prints the rule for the parity test, which parses the ADR text and fails when the two disagree: the ADR is the source. |
| `land-docs-only.sh <pr>` | **Lands a docs-only PR with no review cycle** (task 355, ADR 0141 decision 1). Nothing else: `docs-only.sh` must pass, `git merge-tree --write-tree origin/main <head>` must be clean, `check-task-filed.sh --count` must be 0 and `scripts/pr-precheck.sh origin/main` must find no BLOCK — then it hands over to `merge-pr.sh`, so an open review claim still blocks. It fetches origin main and the PR head ref first (a failed fetch is exit 2), reads the PR head SHA once, runs every gate on that SHA and merges with `--match-head <sha>`. It refuses unless HEAD is the PR's own head (the gates read the tree they stand in), never schedules itself, and never applies a migration or deploys. |
| `lane-guard pre` · `lane-guard notices` | The Claude Code hook (`.claude/settings.json`, project scope): `pre` refuses a write in a tree another live session holds (task 154, see below); `notices` delivers the holding session its co-tenant notices. |
| `session-start-notice` · `session-start-notice --install` · `session-start-notice --check` | The Claude Code **`SessionStart` hook** (task 297; JSON form, installed copy and one-line rule, task 326): reads the hook's JSON on stdin and, when the session's folder is the repository's **main checkout** and that repository has at least one linked worktree, prints the hook's JSON — a `systemMessage` for the person and the same line as `hookSpecificOutput.additionalContext` (`hookEventName: "SessionStart"`) for the model: this is the shared checkout, the branch it is on, how many commits it is behind `origin/main` as last fetched (never fetches), and to open the worktree folder as the workspace (`lane ls` lists them). Silent and exit 0 in every other case (bad input, no git, any internal failure), ~0.15 s a run. `--install` copies the script to `~/.claude/hooks/session-start-notice` and prints that path for the user-scope entry; `--check` exits 1 and names the difference when that copy is missing, stale or not executable. The installed copy stands down when the checkout's own `.claude/settings.json` registers the hook, so a session gets one line, not two. `SESSION_START_NOTICE_HOME` replaces `~/.claude` (tests only). A hook, not a command: run by path, never symlinked — see below. |
| `dispatch.sh --lane <name> --task <id> [--series <s>] [--eta <min>] [--message-file <path>] [--wait] [--no-preflight] [--force] [--force-shared-checkout] ["<msg>"]` | Backgrounds an `ask-pi` call and leaves a JSON status record under `.claude/dispatch/` for polling instead of blocking. `--message-file` takes the brief from a file; `--wait` blocks for the worker and returns its exit code, stopping at the record's deadline plus `DISPATCH_WAIT_GRACE` (300 s, then exit 6); `--eta` digits are decimal (`08` is 8 minutes, never octal); a preflight refuses (exit 5) when it cannot prove the worker will reach its model's API — no HTTP response, **curl missing**, or a `baseUrl` that is not a URL string, each named as itself. **Enforces ADR 0086's two concurrency rules before it launches anything** — see below. |
| `ticket.sh start --series <s> --task <NNN-slug> --owns <paths> --eta <min> --brief <file> [--wait] [--force] [--force-battery]` · `ticket.sh redispatch --series <s> --task <NNN-slug> --eta <min> --brief <file> [--wait] [--force] [--force-battery]` · `ticket.sh land <pr> --reviewed <sha> [--read-unreviewed] [--dry-run] --fail-first <suite> [args…]` · `ticket.sh status <NNN-slug \| lane>` · `ticket.sh workers` | **Start a ticket, send it back, land it, and see where it stands with one command each (tasks 292, 322 and 342).** `start` refuses a task the ready list does not name, prints one power line and **refuses before it makes anything** when the Mac is on battery below 7% (`--force-battery` overrides) or the machine's Pi ceiling is already held (the refusal lists every dispatch in flight: lane, task, started, deadline; `--force` is the bypass and reaches `dispatch.sh --force`), cuts `ticket/<s>-<NNN>` from `build/<s>` with no upstream, claims the Pi lane (the ticket's task files are added to its owned paths) and dispatches from the new worktree with `--message-file`, passing `--wait` through. **Every exit after it cut the branch rolls the branch, lane and worktree back, says so and can be run again.** `redispatch` sends a ticket back on the lane and worktree it already has, with a new brief. `status` and `workers` are the **read-only lander view**: one ticket's records, worker reply, PR, commits, last reviewed sha and `## Review`, or every dispatch in flight on the machine. `land` runs the lander check's five mechanical steps in order (`tasks/README.md` §The lander check), prints the diff since `--reviewed`, then merges through `merge-pr.sh`, fast-forwards `build/<s>`, removes the lane, worktree and ticket branch, and appends one `lands.tsv` row under a header row — dispatches, rounds, verdicts, models, send-backs, the unreviewed lines and the seconds asleep beside the eight columns build 2 had (task 320; the table below is the contract). See below. |
| `fail-first.sh --suite <test file> --restore <path>[,<path>…] --from <ref>` · `fail-first.sh --suite <test file> --env NAME=VALUE` · `fail-first.sh --copy [--restore <paths> --from <ref>]` · `fail-first.sh --remove <path>` | **One command proves a ticket's new test fails on the old code (task 319).** Run from the ticket worktree: it copies the worktree's tracked files to a temp folder, puts the named paths back as `<ref>` had them (a path `<ref>` did not have is removed), and runs the suite once on the tip and once in the copy — `--env` does the second run with a seam set instead. Each run prints its exit code and its `^ok`/`^FAIL` counts plus the first FAIL lines, and the row a land records gets one `result:` line. Exit `0` only when the tip passed and the second run failed; `1` when it proved nothing (the tip failed, or both runs passed); `2` a refusal that ran nothing — no restored path differed from the tip, the suite file is missing, `<ref>` does not resolve, or `mktemp` failed. The copy is a git repository (the suites read the repo they sit in) and one function makes and removes it, refusing an empty path. `--copy` makes that guarded copy, prints it and leaves it for a review lens; `--remove` takes it away and refuses a path it did not make. `ticket.sh land --fail-first` runs it. Tests: `tests/fail-first.test.sh`. |
| `orchestrator-count.sh [--quiet]` | The only scheduled counter: counts unfiled done-tasks, overdue dispatch records, stale PRs, and (task 079) any loaded `com.navigate*`/`com.navigateops.*` launchd job sitting at a non-zero, non-`-` exit status. Own exit codes: `0` nothing crossed, `2` something crossed AND every escalation of it landed in `PENDING/`, `1` a crossing's escalation FAILED to land (or the script couldn't establish its own bearings), `64` bad usage — `2` is reserved for "found something and told someone", never conflated with a real failure. Run under `run-job.sh`, which maps that `2` to a clean launchd status; see its header for the full contract. |
| `<report-lines> \| escalate-crossing.sh <kind>` | The "tell someone" half of the counter: turns a crossing into one file per finding kind in `workspaces/coo/decisions/PENDING/`, landed on `main` through a throwaway worktree. Re-runs update that file rather than piling up duplicates. Called by `orchestrator-count.sh`, not by hand. |
| `ask-rawls --ask <task-slug>:<blocker-slug> "<question>" [--live]` | Dispatcher → Rawls. One fresh Fable call per ask on the Claude plan, capped at $6 per call (two calls per key, so $12 per question), fanned out in parallel, reading only a snapshot of `main`'s record. A cited ruling lands in `workspaces/rawls/ANSWERS.md` on `main`; an uncited question comes back as residue (`--live`) or goes to `PENDING/`. Two calls per issue key, then a human. **Refuses executors** (Pi sessions, bridge chains) and is deliberately **not** linked into `~/bin`. Procedure: `.claude/skills/dispatcher-blocked/`. |
| `check-task-filed.sh [--range <git-range>] [--count]` | Pre-merge gate — fails if a `tasks/inbox/*.md` file is `status: done` but hasn't been moved to `tasks/done/`. `--count` prints a bare count (then offending paths) for `orchestrator-count.sh` to consume, instead of parsing prose. |
| `frontier-ready.sh [--branch <ref>] [--series <spec>]` | The frontier's ready list: prints the tasks the orchestrator may dispatch, one `NNN-slug` per line, most-direct-dependents first. A task is ready when it is in `tasks/inbox/`, its `status: queued`, every `blocked-by` (inline or block-style) names a `done` task, and its `_planning/<series>-YYYY-MM-DD.md` spec has an `## Approved` line carrying a signed `YYYY-MM-DD` date (a template placeholder, HTML comment, or fenced block never counts). `--branch` reads a named ref without checking it out; `--series` limits to one spec (zero or several matching files is an error). Exit codes follow `orchestrator-count.sh`: `0` clean list, `2` graph error found and reported (cycle, dangling or bare-number `blocked-by`, ambiguous spec, one task stem in both `tasks/inbox/` and `tasks/done/`), `1` could not read (including a ref with no `tasks/inbox`), `64` bad usage. |
| `health-check.sh [--update-baseline]` | The weekly health check (task 079), rebuilt model-free: deno lint/check/test over `supabase/functions`, Supabase advisors diffed against a committed baseline (`health-baseline.txt`), and a pipeline snapshot (shipment legs, alerts, unacked notifications, the two tracking cron jobs). Writes a dated report to `HEALTH_REPORT_DIR` (default `~/Library/Logs/navigate-ops/health/`, never committed). Own exit codes: `0` clean/watch, `2` a real RED AND the PENDING escalation landed, `1` a check could not run at all OR a RED's PENDING write failed (could-not-report is the same bucket as could-not-run — that distinction is the whole point of task 079), `64` bad usage. A RED lands one `workspaces/coo/decisions/PENDING/health-check.md`, same dedupe shape as the counter's crossings. Run under `run-job.sh`, which maps `2` to a clean launchd status. |
| `launchd/run-job.sh <repo-relative-script> [args...]` | What every `com.navigate*` launchd job actually invokes (task 036). Refreshes the dedicated jobs checkout (`~/Sites/navigate-ops-jobs`, gitignored from this repo, a `git worktree` detached at `origin/main`) to `origin/main`, refuses to run against it if it's missing or dirty, then runs the named script relative to it (not `exec` — it stays alive to translate the exit code). **The exit-code contract**, so `launchctl list`'s status column can't conflate "found something and reported it" with a crash: target exit `0` → `0`; target exit `2` (ran, found something, reported it successfully) → `0`, logged as `findings reported (rc 2)`; anything else (could not run, or ran but could not report) → passed through unchanged, which is what `failing-launchd-jobs` (arm 5 of `orchestrator-count.sh`) watches for. Never run by hand outside a test — see `launchd/INSTALL.md`. |
| `tests/run-all.sh [suite ...]` | **The one command that runs the bridge's own tests.** Finds every `*.test.sh` beside it by glob (a new suite needs no edit here), runs them one at a time, prints one line per suite — `ok`/`FAIL`, name, seconds, last non-blank line — then a total. Exit codes match the other gates: `0` all passed, `1` could not run (bad `RUN_ALL_DIR`, no suites, `mktemp`), `2` one or more failed or timed out, `64` bad usage. `RUN_ALL_TIMEOUT` (default 300) kills a suite that overruns by its own pid; a failed suite's output is kept and its path printed on stderr (`RUN_ALL_LOG_DIR`, default `$TMPDIR`). `tests/run-all.sh lane dispatch` runs only those two. Tests: `tests/run-all.test.sh` (fake suites through the `RUN_ALL_DIR` seam). |

`dispatch.sh`, `ticket.sh`, `fail-first.sh`, `orchestrator-count.sh`, `escalate-crossing.sh`,
`check-task-filed.sh`, and `frontier-ready.sh` carry a `.sh` extension and are invoked by path, unlike `ask-pi` / `ask-claude` / `lane`
above, which are extensionless commands symlinked into `~/bin` (`sync` is extensionless too but is run by its
repo path, not linked). `lane-guard` and `session-start-notice` are extensionless like those,
but are **not** symlinked into `~/bin` either: they are Claude Code hooks, invoked by path from
`.claude/settings.json` (`"$CLAUDE_PROJECT_DIR"/tools/agent-bridge/lane-guard pre`,
`"$CLAUDE_PROJECT_DIR"/tools/agent-bridge/session-start-notice`), so every worktree runs its
own checkout's copy. The consequence for `session-start-notice`: because a hook is read from
the checkout the session launched in, a shared checkout parked on a branch older than the
commit that adds this entry has neither the entry nor the script and stays silent until that
checkout is updated. **Decided by Brendan on 2026-10-12 (task 313), built by task 326:** the
hook is also registered at user scope (`~/.claude/settings.json`), from a copy of the script
that does not live in any checkout, and its line is shown to him as well as added to the
model's context.

**The installed copy (task 326).** `tools/agent-bridge/session-start-notice --install` copies
the script to `~/.claude/hooks/session-start-notice` and prints that path; `--check` exits 1
and names the difference (missing, stale, not executable) when that copy no longer matches the
checkout's, and 0 when it does. **Refresh it after any change to the script:** from a checkout
that has the change, run `--install` again, then `--check`. The user-scope entry in
`~/.claude/settings.json` is exactly:

```json
{
  "hooks": {
    "SessionStart": [
      { "hooks": [ { "type": "command", "command": "/Users/bsingbeil/.claude/hooks/session-start-notice" } ] }
    ]
  }
}
```

The command path is the one `--install` printed (on this machine,
`/Users/bsingbeil/.claude/hooks/session-start-notice`); `$HOME` would do the same, since hook
commands run through a shell. It sits beside any other `SessionStart` entry in that file, and
the project entry stays too —
Brendan chose the user entry *as well as* it. **One line per session:** both run in the same
session, so the installed copy checks whether the checkout's own `.claude/settings.json`
registers `session-start-notice` **and** that checkout's copy of the script prints the JSON
form, and stays silent when both hold — the project entry prints. In a shared checkout whose
branch predates the project entry, or predates the JSON form (task 297 only, plain text: a
`systemMessage` Brendan never sees), only the installed copy prints. Both arms are pinned in
`tests/session-start-notice.test.sh`. That's
the whole distinction — the `.sh` scripts are in-repo gates and helpers, not
standalone commands, so they were never symlinked out. **`ask-rawls` is the one
exception**: extensionless like a command, but deliberately *not* symlinked into
`~/bin` — putting Rawls on every agent's command path would widen the reach its
executor refusal exists to narrow, so the Dispatcher runs it by its repo path.
`lib/frontmatter.sh`, `lib/in-flight.sh`, `lib/lane-core.sh`, `lib/portable-date.sh`, and `lib/repo-root.sh` are shared
helpers sourced by the `.sh` scripts and the extensionless commands (and, for `repo-root.sh`, by `dispatch.sh`
too — it resolves the one shared main-checkout directory regardless of which
worktree a script runs from, the same way `lane` resolves `lanes.tsv`'s
location). `lib/lane-core.sh` is the one `lane` and `lane-guard` both source, so
"who is live" and "what tree is this" can never drift into two answers. `lib/in-flight.sh`
(task 341) is the one "is this dispatch in flight?" predicate — `record_field`,
`record_in_flight` and `close_lost_record` — read by `dispatch.sh`'s two ADR 0086 gates,
by `ticket.sh start`'s ceiling check and by `ticket.sh workers`, so none of them can count
different sets. `lib/land-on-main.sh` is the one write path to `main`'s tree — the
throwaway-worktree drain `escalate-crossing.sh` and `ask-rawls` both use, so it
exists once. `lib/pending-writer.sh` (task 121) is the one PENDING-file writer (`write_one` +
`pending_frontmatter`: one open file per kind, a re-run keeps `created:` and bumps `last-seen:`),
shared by `escalate-crossing.sh` and `health-check.sh` so their dedupe rule cannot drift apart.
None of them are meant to be run directly. Tests for `ask-rawls`
live in `tests/ask-rawls.test.sh` (stubbed `claude`, fake origin, no model calls).
Run them all with `tools/agent-bridge/tests/run-all.sh`; the runner's own test is
`tests/run-all.test.sh`. The symlink resolver every sibling-locating script
shares is checked by `tests/symlink.test.sh` (throwaway repo, links in a folder
with no `lib/` beside them, plus a scan of the real worktree).

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
writes; a record counts as in flight only if `finished` is still `null` and its
worker is not provably gone — a live pid, or for a record written before the pid
was known, its sibling `.pid` file, its own `deadline`, or a day past its mtime
when the deadline is missing or unreadable. Past that a pid-less record stops
holding the gate, so one crashed worker can't hold it shut.

| Exit | Refusal | Override |
|------|---------|----------|
| `2` | Bad arguments: no brief, both a `--message-file` and a positional message, a missing or empty brief file, a missing `--lane`/`--task`, or a non-integer `--eta`. Also **stdout or stderr is a pipe and `--wait` was not given** (below). | — |
| `3` | Another unfinished Pi dispatch is already running against **this same working tree**. A git worktree is mandatory for every parallel Pi lane — two unattended `--approve` agents on one checkout is a data-loss bug waiting for a slow afternoon. | `--force-shared-checkout` |
| `4` | The **2-Pi ceiling** is already reached. Counts `worker: "pi"` only, and says so: `dispatch.sh` is the only thing that writes records today, so the Sonnet half of "2 Pi + 2 Sonnet" is unenforceable rather than silently enforced. | `--force`, or `DISPATCH_PI_CEILING=<n>` for a session |
| `5` | The preflight cannot prove the worker will reach its model's API: **no HTTP response** (proxy or network), **curl is not installed**, or the provider's `baseUrl` is not an http(s) URL string. Each is named as itself (see the preflight below). | `--no-preflight` |
| `6` | `--wait` only, the worker's fate is unknown (exit 1 is a worker's own code, so it is not reused here): the worker is gone and its record never closed, it closed with no exit code, or **the record's deadline passed `DISPATCH_WAIT_GRACE` seconds ago** — the waiter stopped, the worker may still be running. | — |

**The two overrides are deliberately separate flags.** The ceiling is a
calibration guess (ADR 0086; task 031 sets the real number), so `--force` is a
reasonable thing to reach for. The worktree rule protects against losing work,
so `--force` must not silently switch it off as a side effect of raising the
ceiling. Each prints a loud warning naming the rule it bypassed.

Records gained a `worktree` field for this. A record written before that
(no field) blocks the shared-checkout check rather than passing it — it cannot
prove it is running somewhere else, and the conservative reading is the safe one
for the rule whose failure mode is two agents writing one checkout.

Records also gained a `reason` field (task 320): `ticket.sh start` writes
`first`; `redispatch` writes `sent-back` after a worker that finished (exit 0),
`worker-died` after one that did not (non-zero, `-1` for lost, or never closed),
and `unknown` when no prior record is readable; and `dispatch.sh --reason <text>`
carries whatever a caller passes. `lands.tsv`'s `sent_back` column counts
`sent-back` alone, so a worker that crashed is never counted as work the lander
sent back. A dispatch with no `--reason` records an empty reason, which no
counter reads as either. A record's name is `<lane>-<YYYYMMDDTHHMMSSZ>`; a second
dispatch of the same lane inside that same second gets `_02`, `_03`… rather than
overwriting the first, because two dispatches used to share a filename and
`lands.tsv` counts records, so the earlier one was silently lost. The two
same-second names do not order reliably between themselves (glob and `sort`
collate `_` against `.` by locale), so the readers that need the newer one —
`send_back_reason` and `status`'s worker reply — compare the record's `started`.

A dispatch record normally closes even when its worker dies, and
`orchestrator-count.sh` skips closed records — so **a non-zero `exit_code` on a
finished record is a crash signal**, and the place a worker that exited non-zero
is visible unless someone ran `dispatch.sh --wait`, which returns the same code
to its caller. When the record *never* closes (the launching subshell was killed,
or its closing write failed) the signal is the other shape: `finished: null`
with a dead pid, which `orchestrator-count.sh` reports as overdue/DEAD once past
the deadline (when the deadline is readable), and which `--wait` exits 6 on.

**The next `dispatch.sh` run closes those** (task 341): the gate scan walks the
records anyway, so a record that is still open with a pid that is provably gone
gets its `finished` written, **`exit_code: -1`** — "the worker was lost, not seen
to exit", a value no real exit can produce — its sibling `.pid` file removed, one
line in its own log saying so, and one line on stderr naming it. Before this, such
a record sat open forever (`finished: null` beside a dead `.pid`), reported DEAD on
every counter run until a human deleted it. A live worker's open record is never
touched by the scan, and neither is a pid-less one: nothing proves that worker gone.

Covered by `tests/dispatch.test.sh` (stubbed `ask-pi`, real git worktrees, no Pi
call).

### Waiting, the brief file, and the preflight

**Without `--wait`, `dispatch.sh` returns at once** — the record path on stdout
line 1 and the worker pid on line 2, while `ask-pi` keeps running in the
background. Redirect stdout to a **file**: the detached worker subshell inherits
the caller's stdout, so a pipe caller stays blocked until the worker exits (and
killing that caller kills the worker). That is an accident of inheritance, not a
wait — so **`dispatch.sh` now refuses (exit 2) when stdout *or* stderr is a pipe
or an agent harness's socketpair, and `--wait` was not given**, naming both ways
out: redirect to files, or pass `--wait`. A socketpair counts because Node-based
harnesses (Claude Code's Bash tool, Pi itself) hand children AF_UNIX sockets as
stdio and wait for EOF on them exactly as they would on a pipe. On ticket 290 a `dispatch.sh … | grep -v … | tail` held the call for
its 180-second limit, and stopping it killed the worker; a file-redirected
stdout with a piped stderr blocks the same way, because the subshell holds both.
A pipe is fine with `--wait`, which returns when the worker does.

`--wait` is the real wait: it blocks until the worker exits, prints the **last
20 lines of the dispatch log**, and exits with the worker's own exit code. It
holds the machine awake with `caffeinate -i -w` where `caffeinate` exists (macOS)
and works without it elsewhere. The record path is still printed first. **The
exit code is unambiguous**: a record path on stdout line 1 means it is the
worker's; a run that prints no record path refused before launch, so the code is
`dispatch.sh`'s own (2, 3, 4 or 5); **exit 6** means the worker's fate is unknown —
its record never closed or carried no exit code. A worker that dies without ever
closing its record gets a 5 s grace, then exit 6 naming the log — never a silent
0. **Interrupting `--wait` stops the waiter, not the worker**: the worker is
disowned and the record is its handle, so a Ctrl-C/SIGTERM prints the record path
and exits 130 while the worker keeps running. Run `--wait` as a background task
when the ETA may exceed your command timeout, and poll the record to re-attach.

**`--wait` has an upper bound** (task 342): it stops waiting when the record's own
`deadline` has passed by `DISPATCH_WAIT_GRACE` seconds (default **300**, the seam the
tests set), prints the log tail, and exits **6** saying the worker may still be
running. `ask-pi` has no timeout of its own, so without a bound a wedged worker
held the waiter — and `caffeinate` — for ever. 300 s covers a worker that answers
at its deadline and then writes its closing record; a grace that scaled with
`--eta` would let a wedged worker hold a caller for hours. The deadline comes from
the record (the field a poller reads), falling back to this run's own when it is
missing or unreadable. Stopping the wait never stops the worker: it is disowned
and the record is its handle.

`--message-file <path>` takes the brief from a file instead of a positional
message. Giving both, or a missing or empty file, is refused with **exit 2**
before anything is written.

The **preflight** runs before the ADR 0086 gate scan, the log truncation and any
record write. It resolves the worker's model the same way the record does
(`PI_BRIDGE_MODEL`, else Pi's default), looks the provider's `baseUrl` up in
Pi's own `models.json` (only that field — never the API key), and makes one
request to that base URL with the environment the worker will inherit (so a
broken proxy breaks it the same way). **Any HTTP status counts as reachable** —
a 401 is fine; no response at all is the failure (the 2026-10-10 worker got curl
exit 35, connection reset, through the proxy while the bypassed request answered
in 0.14 s). No response → **exit 5**, no record, and a message naming the URL,
the error, and `curl --noproxy '*' …` as the check to run next (if that answers,
the host belongs in `NO_PROXY`). When the provider's base URL cannot be resolved
— a Pi built-in provider such as `anthropic` or `gemini`, or simply no
`models.json` — one line on stderr says the preflight was skipped and for which
model, and the dispatch continues.
`DISPATCH_PREFLIGHT_URL` overrides the lookup (the tests use it so no case
touches the network); `--no-preflight` skips the check silently.

**The preflight names the reason it could not run** (task 342), instead of reading
every cause as an unreachable API. A missing `curl` gets its own refusal (exit 5)
saying curl is missing and which command name was looked for (`DISPATCH_CURL` is
the seam the tests use); a `baseUrl` that is not an http(s) URL string — `jq`
prints an object as JSON, and curl then rejected it — gets a refusal naming the
`baseUrl` value and saying which field in `models.json` to fix. Neither message
claims the network failed, because nothing was proven about it.

**The provider's hosts bypass the proxy, from a named list.** Before the
preflight, `dispatch.sh` appends that list to `NO_PROXY` **and** `no_proxy`
(keeping whatever the caller had) and exports both, so the preflight `curl` and
the worker it launches both reach the provider directly. The list is in
`dispatch.sh` itself (so `sync` keeps mirroring one file):
`deepseek.com,.deepseek.com,api.deepseek.com` by default, replaced by
`DISPATCH_BYPASS_HOSTS=<comma-separated hosts>` (one variable; empty adds
nothing). It is a *named* list rather than "the provider's host" because a
provider outside China needs the proxy. This is what a caller's window cannot
be trusted to supply: VS Code hands each window the environment it captured at
launch, which is why build 2's orchestrator typed a ~330-character `NO_PROXY`
prefix onto nine starts.

## Starting and landing a ticket (`ticket.sh`)

One command starts a build ticket, one sends it back and one lands it (tasks 292, 342 and
320).
All three read the same `.claude/dispatch/` records `dispatch.sh` writes in the main
checkout and the same lane registry `lane` writes, so nothing is pasted between windows.

```bash
tools/agent-bridge/ticket.sh start --series <s> --task <NNN-slug> \
    --owns <paths> --eta <minutes> --brief <file> [--wait] [--force] [--force-battery]
tools/agent-bridge/ticket.sh redispatch --series <s> --task <NNN-slug> --eta <minutes> \
    --brief <file> [--wait] [--force] [--force-battery]
tools/agent-bridge/ticket.sh land <pr> --reviewed <sha> [--read-unreviewed] [--dry-run] \
    --fail-first <suite> [args…]
tools/agent-bridge/ticket.sh status <NNN-slug | lane>
tools/agent-bridge/ticket.sh workers
```

`start` refuses a task `frontier-ready.sh --branch build/<s> --series <s>` does not name, cuts
`ticket/<s>-<NNN>` from the tip of `build/<s>` with no upstream, claims the Pi lane (its
worktree is created by `lane new --worktree`) with the ticket's `tasks/inbox/` and
`tasks/done/` files added to the owned paths, then dispatches from that worktree with
`--message-file`. It prints the lane, branch, worktree and record paths and **the worker's
pid**. Without `--wait` it returns once the worker is launched; with `--wait` it passes the
flag through and exits with the worker's code. `--eta` digits are **decimal**: `08` is 8
minutes, never octal (a bare `$(( ))` aborts on `08` and reads `010` as 8).

**`--force` passes `dispatch.sh --force`** and nothing else: it is the ceiling's bypass, so a
forced start skips the advisory ceiling check above and lets `dispatch.sh`'s own gate warn and
proceed. `--force-battery` stays the battery's — separate flags for the same reason `--force`
and `--force-shared-checkout` are separate: one is a calibration guess, the other a data-loss
risk.

**Every failed start rolls back what it made.** After the branch is cut, any exit — a `lane
new` refusal (even one that already added the worktree), an unreadable worktree path, a
`mktemp` failure, a `dispatch.sh` refusal — takes one `EXIT` trap that removes the worktree
(found by its branch in `git worktree list`, so a half-run `lane new` is covered), releases
the lane and deletes the branch, then prints `rolled back the branch … the lane … and the
worktree …`. The coordinate lines are **not** printed on that path: they describe things that
no longer exist. The old inline rollback skipped four exits and left the worktree behind when
`lane new` failed after adding it, so the next start refused "branch already exists".

**The dispatch record is the point of no return, not the stdout line.** `dispatch.sh` writes
the record before it launches anything, so a record this run wrote means a worker exists even
if the record path never reached this shell (a Ctrl-C on a foreground `start --wait`, a lost
stdout). The trap then leaves the branch, the lane and the worktree in place and prints where
they are — deleting the tree the worker is writing in would be the lost worker this build
exists to prevent. Two smaller guards from the same review: a lane name already in the
registry is **refused before the branch is cut** (`lane rm <lane>` once its branch and worktree
are gone), and the trap only releases a row whose branch is the one this run cut, so a
half-landed ticket's or another session's row is never swept up. If a cleanup step itself
fails, the message names the path or the row it could not remove instead of claiming nothing
was left behind.

**It checks the machine can take a worker before it makes any of that** (task 341). Two
refusals, both after the ready-list check and before the branch is cut, so nothing is left
behind to roll back — the old path spent 20 to 25 seconds making all three and then undoing
them when `dispatch.sh` refused:

- **The Pi ceiling.** The same `record_in_flight` (`lib/in-flight.sh`) `dispatch.sh` uses, so
  the two cannot count different dispatches; the ceiling is one number for the whole machine
  (ADR 0086), so another session's worker holds it too. The refusal lists each dispatch in
  flight — lane, task, started, deadline — and makes nothing.
- **The battery.** Every run prints one power line: the source, the battery percentage and
  whether the lid is closed (`ticket.sh start: power — AC power, battery at 100%, lid open`).
  On battery below **7%** it refuses (Brendan, 2026-10-12) unless `--force-battery` is given,
  which says loudly that it bypassed the floor. A closed lid is **reported, never refused on**
  and never a reason to suggest a power setting: it is Brendan's deliberate pause
  (2026-10-11). An unknown source or percentage cannot prove a shortfall, so it does not
  refuse. The reading sits behind `TICKET_POWER_CMD` (a command printing
  `source:`/`percent:`/`lid:` lines) so the tests never read the real machine.

**The brief it sends is the caller's file plus one line**: "Follow `tasks/README.md` §Review
before the PR and §Worker rules." — appended once (skipped if the file already carries it), on
a copy, so the caller's file is never modified. A brief therefore holds only what is special to
its ticket, and the two rule sections have one home.

**`redispatch` sends a ticket back** (task 342). Twice in build 2 the lander check refused a
ticket and the orchestrator had to use the pilot's hand-written `redispatch.sh`; this is that
command. It takes `start`'s `--series`, `--task`, `--eta`, `--brief`, `--wait`, `--force` and
`--force-battery` (no `--owns`: the lane's owned paths are already recorded) and dispatches a
new brief on the lane and worktree the ticket already has, printing the same lane, branch,
worktree, record and pid lines. It refuses when no lane matches, its worktree is gone, or a
dispatch for the lane is still in flight (two workers on one tree), and it applies the same
battery floor. It rolls nothing back — it made nothing, so a refusal leaves the lane and
worktree exactly as they were. The ceiling is `dispatch.sh`'s own gate, which `--force`
reaches there; `redispatch` never re-cuts the branch.

`land` runs the five mechanical steps of `tasks/README.md` §The lander check in order and
stops at the first that fails, naming it: (1) the ticket worktree is at the PR's head and every
path in `git diff <base>...<head>` is under the lane's owned paths; (2) the suites the ticket
names pass on the ticket worktree — a `tests:` frontmatter line on the queued copy of the task
file (on `build/<series>`) names them (`tests: [<path>, <path>]`, paths from the worktree root,
none outside it), and a ticket that names none gets `tools/agent-bridge/tests/run-all.sh`, so a
ticket in another room no longer lands on the bridge's suites; a `tests:` line added in the
ticket branch is ignored, so a worker cannot swap the gate; they run under `caffeinate -i` where it exists, holding the Mac awake the way
`dispatch.sh --wait` does (task 343); (3) the PR body's
`## Review` section has one `Round <n>: <GREEN|YELLOW|RED> (<models>) reviewed <sha>` line at
the start of a line per round, and a **RED anywhere in the last round refuses the land**,
whatever follows it (Brendan, 2026-10-12, task 343). The last round is everything from the last
`Round <n>` line to the end of the section, so a round-1 RED with round 2 after it does not
refuse, and a round that says GREEN and then records `Spec axis: RED` does — which is why
`tasks/README.md` puts each round's details below its own line. A negated RED (`no RED`,
`0 RED`) is not a verdict; (4)
the arguments after `--fail-first` (which goes **last**: the rest of the command line is the
script's own) are run as `fail-first.sh` from the ticket worktree, and a non-zero exit refuses
the land — `--fail-first-manual "<what was run and what it showed>"` is
the stand-in for evidence the script cannot produce (task 319); (5) `git diff <reviewed>..<head>` is printed
and a non-empty diff needs `--read-unreviewed`. A `## Review` with no round line is refused:
the counters cannot read a review that was never written down as a line (task 320), and the
refusal says which shape it wants. It
refuses when the `build/<s>` worktree is missing or not on `build/<s>`, the ticket worktree has
uncommitted files, or a dispatch for the lane is still running. Then it calls `merge-pr.sh
<pr>`, fast-forwards the local `build/<s>` from `origin`, releases the lane, removes the
worktree, deletes the ticket branch locally and on origin, and appends one tab-separated row
to `.claude/dispatch/lands.tsv` under its header row. Once the PR has merged the row is written
even if a removal step fails, and the failures are named; `merge-pr.sh` prints the PR's state
after the merge, so a caller never needs a second call to learn that it merged. **A `land` that
stopped after the merge can be run again** (task 343): a PR gh reports as already merged repeats
no step, merges nothing and goes straight to the cleanup and the row — a row already holding
that PR is not appended twice, and a re-run's `fail_first` column reads `not run` rather than
claiming a proof it did not make. A re-run is recognised by the `land-<pr>.pending` marker the
first run writes just before it merges (removed once the row is written), so a PR merged some
other way — a raw `gh pr merge`, the web UI, `merge-pr.sh` on its own — is refused instead of
being cleaned up and counted as a gated landing. A `git ls-remote` that fails is not read as "the origin branch
is already gone": the failure is named and the run says so. `--dry-run` prints the unreviewed
diff, the row it would append **with every column named**, and the mutation steps, without
running the tests or changing anything.

**`lands.tsv` is the counters' input** (task 320) — one header row, then one row per landed
ticket. The header is written when the file is created, and added once above an older
headerless file, whose rows keep their eight values and read `-` in every column added later.

| # | Column | Read from |
|---|--------|-----------|
| 1 | `date` | the landing date, UTC |
| 2 | `series` | the PR's base, `build/<series>` |
| 3 | `task` | the lane's task file |
| 4 | `pr` | the PR number |
| 5 | `reviewed` | `--reviewed`, resolved to a sha |
| 6 | `head` | the PR's `headRefOid` |
| 7 | `worker_seconds` | sum of `finished - started` over the lane's records; time on the wall, so it includes a sleep inside a dispatch unless column 14 is subtracted (the 10 h 51 m against a 75-minute estimate is one). A record closed as lost (`exit_code: -1`) is not a window at all |
| 8 | `fail_first` | the command `land` ran and both runs' counts (`… --suite <test file> --restore <path> --from <ref> — tip exit=0 ok=12 FAIL=0 \| copy exit=1 ok=3 FAIL=2`), or `manual — <the sentence>` from `--fail-first-manual` (task 319) |
| 9 | `dispatches` | how many dispatch records the lane has, one per `start` and per `redispatch` |
| 10 | `rounds` | how many `Round <n>:` lines the PR's `## Review` has |
| 11 | `verdicts` | each round's colour, in order, comma-separated (`RED,YELLOW`) |
| 12 | `models` | each round's `(<models>)` text, in order, `;`-separated |
| 13 | `unreviewed_lines` | added plus removed lines from `reviewed` to `head` (the diff step 5 printed): whether the never-reviewed tail shrinks |
| 14 | `seconds_asleep` | of the lane's dispatch windows, the seconds the Mac spent asleep, read from `pmset -g log`; `awake = worker_seconds - seconds_asleep`. `-` when the log no longer reaches back to the lane's first window (the OS rolls it, about a week here) |
| 15 | `sent_back` | records with `reason: sent-back`: how many times the lander refused a finished worker's work |

Column 14's source is `pmset -g log` — about 5 MB and 1.5 s, read once per landing — because
it is the machine's only record of sleep and wake; the worker's own session file was the other
candidate and cannot tell a sleep from a long tool call. pmset states the length of the sleep
a `Sleep` line enters (`… 902 secs`), so no wake pairing is needed, `DarkWake` does not end a
sleep, and each span is clipped to the dispatch windows at both ends. A Mac that slept through
a whole dispatch therefore reads its own length, no more.

Columns 9, 10, 11, 12 and 15 need the dispatch records to say why a dispatch happened: `start`
writes `reason: first`, `redispatch` writes `sent-back` after a worker that finished (exit 0),
`worker-died` after one that did not (non-zero, `-1` for lost, or never closed), and `unknown`
when no prior record is readable — which is how a crash is kept out of the send-back count.
`dispatch.sh --reason <text>` carries it.

Tests: `tests/ticket.test.sh` (a throwaway repo with a stub `gh`, a stub `ask-pi`, and stub
power and sleep seams, real worktrees) and `tests/fail-first.test.sh` (a throwaway repo whose
tip has the fix and whose `base` tag does not).

**`status` and `workers` are the read-only lander view** (task 322). Before each of build 2's
seven lander checks the orchestrator made 12 to 17 read-only calls to see where a ticket
stood; `ticket.sh status <NNN-slug | lane>` is that screen in one command, in the lander
check's order: each dispatch record of the lane (started, deadline, finished, exit code,
whether its pid is alive); the worker's final reply from the newest log, with the `ask-pi`
banner and the extension warnings Pi prints at the top of every log removed; the PR's number,
state and base; the ticket branch's commits since `build/<series>`, one line each; the sha the
PR's **last** `Round <n>` says it reviewed, with `git diff --stat <sha>..ticket/<lane>`; and
the PR's `## Review` section whole. A part that does not exist yet prints `none` and the
command still exits 0 — a last round that states no reviewed sha prints `none` rather than
guessing at a fix commit. `ticket.sh workers` lists every dispatch in flight on the machine
(any series, any session) — lane, task, started, deadline, minutes left, pid alive — through
the same `record_in_flight` (`lib/in-flight.sh`) that `dispatch.sh`'s ceiling counts, so the
two can never disagree; a pid-less record younger than its deadline is listed as such, and a
live worker past its eta shows `overdue`. Neither command writes a file or moves a ref (they
resolve the registry path without `lane_registry_path`, which creates the header row), and
their only `gh` call is a read-only `pr list`.

`lane new --worktree` adds the worktree quietly: git's checkout progress
(`Updating files: NN%`) is asked off with `git worktree add -q` and its stderr is
captured, so nothing from it reaches the caller — a failure reprints it all and
exits 1. That progress is why the orchestrator once piped `lane new` through a
filter, and a pipe loses the coordinates block with it (ticket 321).

## What `lane` refuses, and why — one writer per tree (tasks 107 + 154)

The Claude-side twin of `dispatch.sh`'s exit 3 above. **`lane new` refuses (exit 3) to claim a
directory held by ANOTHER live Claude session**, and now **`lane-guard pre` refuses the write
itself**, so a session that never claims anything is stopped at the edit, not just visible to
`lane who`. A tree is "held" when (a) another live Claude session's `cwd` resolves to that tree,
or (b) an existing lane records that `dir` and its `claimed_by` session is still live.
Live-session source: `~/.claude/sessions/*.json` (`pid`, `sessionId`, `cwd`, `name`, `status`,
`startedAt`); a session is live if its `pid` is. CEO decision 2026-09-24:

| Access | Rule | Override |
|---|---|---|
| Read-only co-tenancy | Allowed, as long as both sessions know. `lane who [path]` lists every live session and every lane in a tree (read-only, exit 0). | — |
| Claiming the tree to write | Refused (exit 3), naming the holder. | `--share-worktree` — its own named flag, not `--force`. Prints a loud warning naming the rule bypassed and tells you to `SendMessage` the holder. |
| **Writing in a held tree** | Refused (exit 2) by the `lane-guard pre` hook on every `Edit`/`Write`/`MultiEdit`/`NotebookEdit` and write-looking `Bash` command. | Hold a lane claim on the tree (each side's own `--share-worktree` claim lets both write), or be a holder — in the main checkout that means having written there inside the last 30 minutes — or be the only live session there (linked worktree). |

- `lane ls` resolves each lane's holder at print time: `SESSION` is the claiming session's name +
  short id, `STATE` is `live | STALE | unknown`. `unknown` means the claimant's liveness is not
  observable here: no `claimed_by`, or a Pi claimant, whose session id never appears in Claude's
  session files. Nothing is auto-removed.
- `lane new` detects a linked worktree from `--git-common-dir` vs `--git-dir`, whatever flags were
  passed, and attributes the agent from the environment (`claude` if `CLAUDE_CODE_SESSION_ID`,
  else `pi` if `PI_SESSION_ID`, else `--agent` is required). A claude lane's "reach it" line is
  `SendMessage to "<name>"`, never `ask-pi`.
- **`--worktree` always lands in the same place (task 200).** `lane new <name> --worktree`
  creates/uses `<main-parent>/<repo>-<name>` — next to the MAIN checkout that holds the shared
  `git-common-dir` — whether it ran from the main checkout or from inside another worktree. Run
  from a nested worktree (`.claude/worktrees/foo`), it no longer nests the new one under that
  worktree. A caller reads the path from the printed `directory` line instead of predicting it.
- **Sessions are filed by working directory, and it follows `EnterWorktree`.** A session that moved
  into a worktree is recorded under that worktree, not the main checkout, so `lane who` on the main
  checkout will not list it. They are separate trees with separate writers, which is correct.
- **Who holds a tree (tasks 154 + 332).** `lane-guard pre` resolves the holder as (a) a live,
  non-review lane claim on the tree — its claimant holds it; (b) additionally, in the **main
  checkout**, **a session holds the tree only while it has written there in the last 30 minutes**
  (Brendan's rule, 2026-10-12, task 299): a write is refused only while another live session holds
  it, and with nobody holding it the write is allowed. An idle window therefore stops
  holding the checkout, a session that quit stops holding at once, and two sessions that both wrote
  inside the window (a share claim, or a fail-open write) may both write. **A recent write also keeps
  holding beside someone else's claim**, so a `--share-worktree` pairing adds a writer instead of
  displacing the one already there. A session that moves into a worktree with `EnterWorktree` keeps
  holding the main checkout until its window ends — the rule is about writes in the tree, not `cwd`.
  The window is one named value, `LANE_GUARD_WRITE_WINDOW_MINUTES`, 30 by default.
  A **linked worktree keeps task 154's rule**: (b) is the **earliest `startedAt`** live Claude
  session whose `cwd` is in the tree. A session file with no `startedAt` counts as latest-started
  (never the earliest holder); if none in the tree has one, there is no `startedAt` holder and the
  write is allowed. The tiebreak is what makes two co-tenant sessions in a worktree non-symmetric:
  exactly one of them is the holder.
- **The write record (ticket 332).** Each write the hook allows in the main checkout appends one row,
  `<epoch seconds><TAB><sessionId>`, to `<git-common-dir>/lane-writes.tsv`: inside the shared git
  dir, so every worktree of the repo shares it, and never in the work tree, so it is never committed.
  Rows older than the window are ignored when read. Once the file passes 64 rows it is rewritten with
  **one row per live holder inside the window**, so it cannot grow without limit and a session that
  quits ages out of it. A record that cannot be read or written prints one stderr line and changes no
  decision (fail open). A write in a linked worktree is not recorded — no rule there reads it.
  **A `Bash` write is the heuristic**, so a FALSE POSITIVE records a hold as well as causing a
  refusal: `mkdir -p /tmp/x`, `cp a /tmp/b` or `ask-pi … > /tmp/out` run from the main checkout
  makes that session a holder for 30 minutes (ticket 332 defines a write as what the hook already
  calls one). Recording only `Edit`/`Write`/`MultiEdit`/`NotebookEdit`, whose target path is exact,
  is the narrower alternative — Brendan's call, not taken here.
  **Claiming a tree is a different rule:** `lane new`'s refusal still decides from live sessions by
  `cwd` (task 154) and does not read this record, so it can name an idle session that `lane-guard`
  no longer counts as a holder.
- **The refusal, in Brendan's order (tasks 299 + 332).** Part 1 is the fact — which session wrote
  there, and how many minutes ago — with ticket 344's "which pattern matched" **inside** it ("…wrote
  here 5 minutes ago; your command counts as a write because of `>`"). A lane claim names the claim
  instead, and a linked worktree names the earliest-started session. Then, in order: 2. "work in your
  own worktree folder" (`lane ls` lists them); 3. "if you must write here, take a share claim and
  name the files you own" (`lane new <name> --share-worktree --owns <path>`); 4. last, "message the
  holder" (`SendMessage to "<name>"`).
- **What counts as a write in Bash (ticket 344).** For the `Bash` matcher the hook is a heuristic
  (`bash_write_ish`): a command is a write when it contains `>`, ` tee `, `sed … -i`,
  `perl … -i`, `mv`, `cp`, `rm`, `mkdir`, `touch`, `chmod`, `ln`, or one of `git add`, `commit`,
  `checkout`, `switch`, `reset`, `restore`, `merge`, `rebase`, `cherry-pick`, `revert`, `stash`,
  `apply`, `am`, `pull`, `clean`, `rm`, `mv`. **`2>&1` and `2>/dev/null` are not writes** — a
  read-only command carrying either is allowed in a held tree — but every other `>` still
  counts, a bare `> /dev/null` and `1>/dev/null` included. Only those two literal forms are
  stripped: `2> /dev/null` (with a space), `2>>/dev/null` and `&>/dev/null` still count. The
  refusal names the pattern that
  matched, inside its first line (the fact): "…wrote here 5 minutes ago; your command counts as
  a write because of `<pattern>`." An `Edit`/`Write`/`NotebookEdit` has no command, so its fact
  line carries no pattern.
- **Fail open.** Any internal error in the hook — missing `jq`, an unreadable registry, a hook
  JSON that won't parse, a corrupt session file — allows the write and prints one stderr line.
  A hook that failed closed would block every edit in every session; that is the worse hazard.
- **The holder is told, once per co-tenant (task 154).** On a refusal (and on a
  `lane new --share-worktree` bypass) the hook appends one line to
  `<git-common-dir>/lane-notices/<holder-sessionId>`. The holding session's own
  `lane-guard notices` hook (UserPromptSubmit + PostToolUse) prints its queue as context and
  removes the lines it delivered. Dedupe keys live in
  `<git-common-dir>/lane-notices/<holder>.seen` (one per co-tenant + tree), so the holder hears
  about a pairing once, not on every write; the `.seen` key survives delivery.
  `lane-guard pre` opportunistically deletes a notice and its `.seen` whose holder session is no
  longer live. The holder is not woken while idle — it sees the notice on its next prompt or tool
  call. Tests: `tests/lane.test.sh` and `tests/lane-guard.test.sh` (stubbed session files, real
  linked worktree, nothing real touched).

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

The check-then-append inside `lane new` is protected by a per-`pr/<n>` `mkdir` lock in the shared
git dir (the same shape `ask-pi` uses for its thread lock, task 156), so two same-instant claims
of one PR cannot both pass the refusal. **`merge-pr.sh <pr>` is the way to merge**: it runs
`lane reviews <pr>` and refuses `gh pr merge --merge` while any claim is open, so no one has to
remember to run the check by hand. A hard-blocking `gh` alias or git hook would close the raw
`gh pr merge` loophole too, but that needs Brendan's go and is not yet decided.

## One lock for the registry — `lane new`, `lane rm`, `lane prune --apply` (ticket 344)

Every command that writes `lanes.tsv` holds **one** lock, `<git-common-dir>/.lane-registry.lock`
(a `mkdir` lock with its pid published by temp-file + `mv`, the same shape as the per-PR one
above), across its whole read-modify-write:

| Command | The read → write window the lock covers |
|---|---|
| `lane new` | the duplicate-name re-check → the append, both taken together at the very end of the claim, so the lock is **not** held across `git worktree add` (a second window claiming another name is never refused for that) |
| `lane rm` | the `grep -q "^<name>\t"` → the `grep -v` + `mv` that replaces the file |
| `lane prune --apply` | the scan that picks the rows → the `awk` + `mv` rewrite (`lane prune` without `--apply` writes nothing and takes no lock) |

Without it, three races could each silently lose a row: two same-instant claims of one name both
passing the duplicate check, and an append landing between another command's read and its rewrite
(the rewrite replaces the file with its own snapshot, so the appended row is gone). A contender
**waits** for this lock (bounded, ~5 s) and refuses with **exit 3** only if it stays held — unlike
a `pr/<n>` lock, which refuses at once because it is held for a whole claim. A lock whose pid names a
dead process is reclaimed, so a killed `lane` cannot wedge the registry. The lock order is always
the `pr/<n>` locks first, then the registry, and `lane rm`/`lane prune --apply` take only the
registry — so the two never deadlock.

## Pruning dead lanes (`lane prune`) — task 295

`lane ls` shows a `STATE` for every lane: `live`, `STALE` (a Claude lane whose session is gone),
and `unknown` (a Pi lane — Pi writes no session file the bridge can check). `lane prune` lists the
lanes nobody holds and, with `--apply`, removes their registry rows.

```bash
lane prune            # list what would be pruned, and why
lane prune --all      # also list the lanes it keeps, and why
lane prune --apply    # remove exactly the listed registry rows
```

Brendan confirmed these rules on 2026-10-12, and `--apply` was first run on the real registry
that day (3 of 25 lanes pruned). Task 329 (his ruling, 2026-10-12) then changed the Pi column: a
Pi lane is judged by the dispatch records, so a Pi lane with no worker running is pruned like a
`STALE` one — the merged-and-clean case included — and the only Pi lane a merged branch does not
clear is one with a dispatch in flight.

A lane is listed **only when its session is not live** and one of these holds:

| Condition | `STALE` (Claude) | Pi (`unknown`, or `--agent pi`) |
|---|---|---|
| a dispatch record for the lane is in flight | — | **kept**, whatever its branch says (the `--all` line names the record) |
| branch tip is an ancestor of `origin/main` as last fetched, and its linked worktree is clean | listed | listed when no record is in flight (no record at all counts) |
| branch no longer exists | listed | listed |
| worktree folder is missing | listed | listed |

- **A live lane is never listed**, whatever its branch or worktree says.
- **A branch that IS the repository's default branch is never called merged** — a branch is
trivially merged into itself. The default branch is read from `origin/HEAD` (falling back to
`main` when that is unset), and local `main` is always exempt too: the command compares against
`origin/main` by contract, so `origin/HEAD` naming another branch must not turn the one real
`main` lane into "merged".
- **The Pi rule follows the agent, not just the state, and reads the dispatch records.** A
`--agent pi` row whose claimant is a Claude session that has since died reads `STALE`, but the
backgrounded Pi worker may still be running — so the rule applies to it too (`unknown` **or**
`--agent pi`). What decides the row is the dispatch records, not the state: `dispatch.sh` writes
one record per worker with its pid and a `finished` time once it ends, so a Pi lane's liveness
*is* observable there. They are read from the main checkout's `.claude/dispatch`, the folder
`dispatch.sh` writes whichever worktree it ran from. "In flight" is **one shared predicate** —
`record_in_flight` in `lib/in-flight.sh`, the same function `dispatch.sh`'s ceiling check and
`ticket.sh workers` read (task 341) — never a second rule that could disagree with them.
  - **A record in flight keeps the lane**, whatever its branch says, and `--all` names the record:
    `kept: Pi lane — a worker is in flight (<record>.json)`.
  - **Records but none in flight** (a closed record, or an open one whose pid is dead) make the
    lane a dead lane: it is listed like a `STALE` one, and the reason says `no dispatch in flight`.
  - **No record at all** also makes it a dead lane, and the reason says `no dispatch record`. That
    is Brendan's ruling (2026-10-12): it covers every `ask-pi` session started before
    `dispatch.sh` existed, and any Pi work that never went through it. He accepted the risk that
    such a row can be cleared while nobody can see the session — an `ask-pi` session ends with the
    Claude session that started it, which is what keeps the risk small. Only the registry row
    goes, as for every pruned lane.
  - So the only Pi lane a merged branch does not clear is one with a dispatch in flight; this
    replaces ticket 295's rule 2 ("a Pi lane is not pruned on a merged branch alone").
  - **One window is left open, on purpose.** `ticket.sh start` claims the lane and dispatches a
    moment later, so between `lane new` and `dispatch.sh` writing its first record a brand-new Pi
    lane has a clean worktree whose tip *is* `origin/main` and no record yet — a concurrent
    `lane prune --apply` sees exactly the merged-and-clean, no-record case Brendan ruled on and can
    drop that row. The ruling does not carve it out and this command does not either: narrowing
    "no record at all" to spare a fresh lane would be a different rule, not this one. The risk has
    the same shape as the `ask-pi` one above, and the row is claimed again with `lane new`.
- **A linked worktree with uncommitted work is not "merged".** `lane new --worktree` points the
branch at the current HEAD, so until the first commit the branch tip *is* `origin/main`. When the
lane's own linked worktree exists and is dirty, the row is kept with that reason instead. The
shared main checkout is not judged — its dirt is not this row's.
- **A detached-HEAD lane is kept**, with "no branch recorded" — `lane new` records the literal
`HEAD` there, and `refs/heads/HEAD` never exists, so it must not read as "branch no longer
exists".
- **A lane that owns ANY `pr/<n>` is always kept**, not just one whose whole `owns` list is
`pr/<n>`: `lane reviews` and `merge-pr.sh` treat a mixed `--owns pr/154 --owns tools/x` as a
review claim too. Reviews are 1:1 with a PR and are never auto-removed (task 109); pruning one
would silently open `merge-pr.sh`'s gate. `--all` shows it as
`kept: review claim — cancel with \`lane rm <name>\` first`.
- **`origin/main` is never fetched by the command.** The output names the `origin/main` commit it
compared against, so "as last fetched" is visible rather than assumed.
- **A lane that is not live but whose branch is unmerged and whose worktree exists is kept.**
`lane prune --all` also shows those lanes, one line each, with the reason each was kept.
- **`--apply` removes exactly the listed registry rows**, the way `lane rm` does — the registry
file and nothing else. It never removes a worktree or a branch; it prints the
`git worktree remove <path>` hint for each lane instead. Run `lane prune` first to see the list.
- **`--apply` takes the one registry lock** (ticket 344) around its scan and rewrite, so it cannot
lose a row `lane new` appends at the same moment — see §One lock for the registry.
- When there is nothing to prune it prints `no lanes to prune` and changes nothing.
- **Liveness is judged from the row's claimant, not from a live session in the same tree.** A lane
whose recorded session died but whose worktree a new live session adopted still reads `STALE`, and
is pruned if its branch is merged/gone or its folder is missing. The tree itself stays protected
(`lane-guard` still sees the live session by cwd); only the registry row's `owns` and its collision
warnings go. Reading a live session's cwd here would keep every row in the shared main checkout,
which the ticket's listing rule does not want.
- **"branch merged into origin/main" also covers a branch with no commits of its own** (a fresh
`--worktree` lane whose tip equals `origin/main`, or a branch cut from an older main and never
committed to). The row is still pruned, and the reason text says "merged" because the tip is an
ancestor of `origin/main` — the definition the ticket sets.

A note on the registry parse: tabs are IFS whitespace, so `read` collapses a row whose `owns`
field is empty (a `lane new` with no `--owns`) and shifts the later fields left — a live lane then
reads as `unknown`. `lane prune` parses the registry with a non-whitespace separator so an empty
field stays a field. The older loops in `lane ls` and `holder_for` still have the collapse; fixing
them is a separate change.

Tests: `tests/lane.test.sh` (a throwaway repo, a throwaway `origin/main`, a live and a dead
session, real linked worktrees, and hand-written registry rows; the real registry is never
touched).

## This directory is the canonical copy

`~/bin/ask-pi`, `~/bin/ask-claude` and `~/bin/lane` are **symlinks into this
directory**. Editing a file **in the checkout `~/bin` points at** is the edit
that reaches the command — no copy step; editing it in your own worktree does
not, until that edit is on the branch that checkout holds (see "What runs is
not the committed version", below).
They are **safe to symlink**: every script here that loads a sibling
file (the `lib/` helpers, `ask-pi`, `review-prompts/`, `scripts/lib/`) resolves
its own symlinks before it looks for that sibling, and `ask-pi` / `ask-claude`
load no helpers, so no `lib` link is needed next to the link in `~/bin`.

**"Safe to symlink" is about loading siblings, not about which checkout a
script reads.** A linked script that reads the repo — `check-task-filed.sh`,
`ask-rawls`, `room-sweep.sh` — reads the checkout its own file lives in, not
the caller's; running it through a link anywhere does not make it read your
worktree.

What runs is **not** "the committed version" — it is the copy in whichever
checkout `~/bin` points at, on whatever branch that checkout is parked on.
`~/bin/lane` today points into the shared `~/Sites/navigate-ops` checkout, which
is not guaranteed to be on `main`; merging a fix here does not change the command
until that checkout carries it. As of 2026-10-10 the hand-made `~/bin/lib` link
must stay until then (removing it is task 286).

Seven other repos carry a mirror of these scripts so the tooling is recoverable
if this checkout is lost. Those mirrors are backups, not what executes. After
changing anything here:

```sh
tools/agent-bridge/sync --check          # which mirrors are stale (exit 1 if any)
tools/agent-bridge/sync                  # copy into each stale mirror's working tree
tools/agent-bridge/sync --via-worktree   # and push every parked mirror for you
```

then commit **and push** any mirror reported as `synced` (copied into its
working tree — by plain `sync`, or by `--via-worktree` for a mirror that is not
parked). A
mirror counts as current when its **pushed** copy matches: `sync` fetches each repo and compares
`tools/agent-bridge/` at its origin default branch, not the checkout. So a
mirror committed but not pushed is still stale, and a checkout parked on
another session's feature branch doesn't make a pushed mirror look stale.
The default branch it compares against is the mirror's `origin/HEAD`; when that is unset,
`sync` asks the remote for its HEAD without writing anything (`git ls-remote --symref origin
HEAD`). A mirror whose remote will not name a default branch, or names one the mirror does not
have, is reported `NODEFAULT` and left alone — it is never assumed to be `origin/main`, which
on a mirror that uses another name (or keeps a stale `main`) would push the scripts to the
wrong branch.
`sync` won't write into a stale repo whose checkout is off its default branch,
isn't exactly at its `origin` tip, or has local changes under
`tools/agent-bridge/`. It reports `PARKED` instead. `sync --via-worktree`
handles every parked mirror in one command: for each stale parked mirror it
adds a throwaway detached worktree at that mirror's origin default branch,
copies the scripts, commits one fixed message naming the canonical commit,
pushes to the default branch, removes the worktree on every exit path, and
never touches the mirror's own checkout, branch or working files. It prints one
line per mirror — `PUSHED`, `CURRENT` or `FAIL` — and nothing is forced, so a
rejected push is a `FAIL` that leaves the remote alone. It exits 1 if any mirror
is not current when it finishes (a failed push, a mirror still only copied into
its working tree, a diverged one, or one with no origin), the same convention as
`--check`. A stale mirror that is not parked is copied into its working tree
exactly as plain `sync` does, so you still commit and push that one yourself;
`sync` refuses to overwrite a working-tree copy that has local edits it would
lose, so a diverged copy surfaces instead of being silently clobbered. That
mtime guard covers the working-tree copy only: on a parked mirror
`--via-worktree` replaces the pushed copy with canonical, and an in-place edit
there is recoverable only from the mirror's own history. **A second
`--via-worktree` run on a mirror it just copied pushes that copy from a
worktree**, leaving the same files uncommitted in the mirror's checkout, one
commit behind; discard them (`git checkout -- tools/agent-bridge && git clean
-fd tools/agent-bridge`) before pulling.

### What `sync` mirrors, and what it doesn't

`sync` copies `ask-pi`, `ask-claude`, `lane`, `lane-guard`, `sync` itself,
`dispatch.sh`, and the `lib/` helpers those source (`lane-core.sh`,
`frontmatter.sh`, `portable-date.sh`, `repo-root.sh`) — generic bridge tooling
with no navigate-ops-specific assumptions baked in, safe to run against any
repo's own `tasks/`.

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

`pi` and `claude` on `PATH`. Pi defaults to `deepseek-flash` (V4.1 Flash, since 2026-09-30; task 196); the Claude side
defaults to `claude-sonnet-5` with a $0.50-per-call budget cap
(`CLAUDE_BRIDGE_MODEL`, `CLAUDE_BRIDGE_BUDGET`, `PI_BRIDGE_MODEL` override).

`health-check.sh` additionally wants `deno`, `psql`, `curl`, `jq`, and (for the
keychain fallback) macOS `security` — each missing tool degrades its own check
to a `note` (deno) or `COULD NOT RUN` (the rest) rather than failing the whole
script. `orchestrator-count.sh`'s `failing-launchd-jobs` arm wants `launchctl`
(`LAUNCHCTL_BIN` override for tests); missing it is a `SKIPPED` note, same
pattern as `gh` for the stale-PRs arm.
