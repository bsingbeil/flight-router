# agent-bridge

Commands and gates that let Claude Code and Pi work together without Brendan
relaying messages between them.

| Command | Does |
|---|---|
| `ask-pi "<msg>"` | Claude Code → Pi. Pi's reply prints on stdout, straight into the caller's context. |
| `ask-claude "<msg>"` | Pi → Claude Code. Claude answers with read-only tools — it reviews, Pi edits. |
| `lane new <name> --owns <path>` · `lane who [path]` | Claims a session id + owned paths (optionally its own worktree) and prints a paste-ready coordinates block for a second terminal window. **Refuses a tree another live Claude session holds** (task 107, see below); `lane who` shows who is in a tree. |
| `lane prune [--apply] [--all]` | Lists lanes whose session is not live and whose branch is merged into `origin/main` (STALE lanes only), whose branch is gone, or whose worktree folder is missing; `--apply` drops exactly those registry rows — never a worktree or a branch. `--all` also shows the lanes it keeps and why. See below. |
| `merge-pr.sh <pr>` | **The merge path (task 156).** Runs `lane reviews <pr>` first and refuses to call `gh pr merge --merge` while any review claim on the PR is open. The orchestrator and the COO merge through this, never a raw `gh pr merge`. |
| `lane-guard pre` · `lane-guard notices` | The Claude Code hook (`.claude/settings.json`, project scope): `pre` refuses a write in a tree another live session holds (task 154, see below); `notices` delivers the holding session its co-tenant notices. |
| `session-start-notice` | The Claude Code **`SessionStart` hook** (`.claude/settings.json`, project scope, task 297): reads the hook's JSON on stdin and, when the session's folder is the repository's **main checkout** and that repository has at least one linked worktree, prints one line — this is the shared checkout, the branch it is on, how many commits it is behind `origin/main` as last fetched (never fetches), and to open the worktree folder as the workspace (`lane ls` lists them). Silent and exit 0 in every other case (bad input, no git, any internal failure). A hook, not a command: run by path, never symlinked. |
| `dispatch.sh --lane <name> --task <id> [--series <s>] [--eta <min>] [--message-file <path>] [--wait] [--no-preflight] [--force] [--force-shared-checkout] ["<msg>"]` | Backgrounds an `ask-pi` call and leaves a JSON status record under `.claude/dispatch/` for polling instead of blocking. `--message-file` takes the brief from a file; `--wait` blocks for the worker and returns its exit code; a preflight refuses (exit 5) when the worker's model API is unreachable. **Enforces ADR 0086's two concurrency rules before it launches anything** — see below. |
| `ticket.sh start --series <s> --task <NNN-slug> --owns <paths> --eta <min> --brief <file> [--wait]` · `ticket.sh land <pr> --reviewed <sha> --fail-first "<cmd>" [--read-unreviewed] [--dry-run]` | **Start a ticket and land it with one command each (task 292).** `start` refuses a task the ready list does not name, cuts `ticket/<s>-<NNN>` from `build/<s>` with no upstream, claims the Pi lane (the ticket's task files are added to its owned paths) and dispatches from the new worktree with `--message-file`, passing `--wait` through. `land` runs the lander check's five mechanical steps in order (`tasks/README.md` §The lander check), prints the diff since `--reviewed`, then merges through `merge-pr.sh`, fast-forwards `build/<s>`, removes the lane, worktree and ticket branch, and appends one `lands.tsv` row. See below. |
| `orchestrator-count.sh [--quiet]` | The only scheduled counter: counts unfiled done-tasks, overdue dispatch records, stale PRs, and (task 079) any loaded `com.navigate*`/`com.navigateops.*` launchd job sitting at a non-zero, non-`-` exit status. Own exit codes: `0` nothing crossed, `2` something crossed AND every escalation of it landed in `PENDING/`, `1` a crossing's escalation FAILED to land (or the script couldn't establish its own bearings), `64` bad usage — `2` is reserved for "found something and told someone", never conflated with a real failure. Run under `run-job.sh`, which maps that `2` to a clean launchd status; see its header for the full contract. |
| `<report-lines> \| escalate-crossing.sh <kind>` | The "tell someone" half of the counter: turns a crossing into one file per finding kind in `workspaces/coo/decisions/PENDING/`, landed on `main` through a throwaway worktree. Re-runs update that file rather than piling up duplicates. Called by `orchestrator-count.sh`, not by hand. |
| `ask-rawls --ask <task-slug>:<blocker-slug> "<question>" [--live]` | Dispatcher → Rawls. One fresh Fable call per ask on the Claude plan, capped at $6 per call (two calls per key, so $12 per question), fanned out in parallel, reading only a snapshot of `main`'s record. A cited ruling lands in `workspaces/rawls/ANSWERS.md` on `main`; an uncited question comes back as residue (`--live`) or goes to `PENDING/`. Two calls per issue key, then a human. **Refuses executors** (Pi sessions, bridge chains) and is deliberately **not** linked into `~/bin`. Procedure: `.claude/skills/dispatcher-blocked/`. |
| `check-task-filed.sh [--range <git-range>] [--count]` | Pre-merge gate — fails if a `tasks/inbox/*.md` file is `status: done` but hasn't been moved to `tasks/done/`. `--count` prints a bare count (then offending paths) for `orchestrator-count.sh` to consume, instead of parsing prose. |
| `frontier-ready.sh [--branch <ref>] [--series <spec>]` | The frontier's ready list: prints the tasks the orchestrator may dispatch, one `NNN-slug` per line, most-direct-dependents first. A task is ready when it is in `tasks/inbox/`, its `status: queued`, every `blocked-by` (inline or block-style) names a `done` task, and its `_planning/<series>-YYYY-MM-DD.md` spec has an `## Approved` line carrying a signed `YYYY-MM-DD` date (a template placeholder, HTML comment, or fenced block never counts). `--branch` reads a named ref without checking it out; `--series` limits to one spec (zero or several matching files is an error). Exit codes follow `orchestrator-count.sh`: `0` clean list, `2` graph error found and reported (cycle, dangling or bare-number `blocked-by`, ambiguous spec, one task stem in both `tasks/inbox/` and `tasks/done/`), `1` could not read (including a ref with no `tasks/inbox`), `64` bad usage. |
| `health-check.sh [--update-baseline]` | The weekly health check (task 079), rebuilt model-free: deno lint/check/test over `supabase/functions`, Supabase advisors diffed against a committed baseline (`health-baseline.txt`), and a pipeline snapshot (shipment legs, alerts, unacked notifications, the two tracking cron jobs). Writes a dated report to `HEALTH_REPORT_DIR` (default `~/Library/Logs/navigate-ops/health/`, never committed). Own exit codes: `0` clean/watch, `2` a real RED AND the PENDING escalation landed, `1` a check could not run at all OR a RED's PENDING write failed (could-not-report is the same bucket as could-not-run — that distinction is the whole point of task 079), `64` bad usage. A RED lands one `workspaces/coo/decisions/PENDING/health-check.md`, same dedupe shape as the counter's crossings. Run under `run-job.sh`, which maps `2` to a clean launchd status. |
| `launchd/run-job.sh <repo-relative-script> [args...]` | What every `com.navigate*` launchd job actually invokes (task 036). Refreshes the dedicated jobs checkout (`~/Sites/navigate-ops-jobs`, gitignored from this repo, a `git worktree` detached at `origin/main`) to `origin/main`, refuses to run against it if it's missing or dirty, then runs the named script relative to it (not `exec` — it stays alive to translate the exit code). **The exit-code contract**, so `launchctl list`'s status column can't conflate "found something and reported it" with a crash: target exit `0` → `0`; target exit `2` (ran, found something, reported it successfully) → `0`, logged as `findings reported (rc 2)`; anything else (could not run, or ran but could not report) → passed through unchanged, which is what `failing-launchd-jobs` (arm 5 of `orchestrator-count.sh`) watches for. Never run by hand outside a test — see `launchd/INSTALL.md`. |
| `tests/run-all.sh [suite ...]` | **The one command that runs the bridge's own tests.** Finds every `*.test.sh` beside it by glob (a new suite needs no edit here), runs them one at a time, prints one line per suite — `ok`/`FAIL`, name, seconds, last non-blank line — then a total. Exit codes match the other gates: `0` all passed, `1` could not run (bad `RUN_ALL_DIR`, no suites, `mktemp`), `2` one or more failed or timed out, `64` bad usage. `RUN_ALL_TIMEOUT` (default 300) kills a suite that overruns by its own pid; a failed suite's output is kept and its path printed on stderr (`RUN_ALL_LOG_DIR`, default `$TMPDIR`). `tests/run-all.sh lane dispatch` runs only those two. Tests: `tests/run-all.test.sh` (fake suites through the `RUN_ALL_DIR` seam). |

`dispatch.sh`, `ticket.sh`, `orchestrator-count.sh`, `escalate-crossing.sh`, `check-task-filed.sh`, and
`frontier-ready.sh` carry a `.sh` extension and are invoked by path, unlike `ask-pi` / `ask-claude` / `lane`
above, which are extensionless commands symlinked into `~/bin` (`sync` is extensionless too but is run by its
repo path, not linked). `lane-guard` and `session-start-notice` are extensionless like those,
but are **not** symlinked into `~/bin` either: they are Claude Code hooks, invoked by path from
`.claude/settings.json` (`"$CLAUDE_PROJECT_DIR"/tools/agent-bridge/lane-guard pre`,
`"$CLAUDE_PROJECT_DIR"/tools/agent-bridge/session-start-notice`), so every worktree runs its
own checkout's copy. The consequence for `session-start-notice`: because a hook is read from
the checkout the session launched in, a shared checkout parked on a branch older than the
commit that adds this entry has neither the entry nor the script and stays silent until that
checkout is updated — noted, not fixed here (registering it at user scope is Brendan's call). That's
the whole distinction — the `.sh` scripts are in-repo gates and helpers, not
standalone commands, so they were never symlinked out. **`ask-rawls` is the one
exception**: extensionless like a command, but deliberately *not* symlinked into
`~/bin` — putting Rawls on every agent's command path would widen the reach its
executor refusal exists to narrow, so the Dispatcher runs it by its repo path.
`lib/frontmatter.sh`, `lib/lane-core.sh`, `lib/portable-date.sh`, and `lib/repo-root.sh` are shared
helpers sourced by the `.sh` scripts and the extensionless commands (and, for `repo-root.sh`, by `dispatch.sh`
too — it resolves the one shared main-checkout directory regardless of which
worktree a script runs from, the same way `lane` resolves `lanes.tsv`'s
location). `lib/lane-core.sh` is the one `lane` and `lane-guard` both source, so
"who is live" and "what tree is this" can never drift into two answers. `lib/land-on-main.sh` is the one write path to `main`'s tree — the
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
| `2` | Bad arguments: no brief, both a `--message-file` and a positional message, a missing or empty brief file, a missing `--lane`/`--task`, or a non-integer `--eta`. | — |
| `3` | Another unfinished Pi dispatch is already running against **this same working tree**. A git worktree is mandatory for every parallel Pi lane — two unattended `--approve` agents on one checkout is a data-loss bug waiting for a slow afternoon. | `--force-shared-checkout` |
| `4` | The **2-Pi ceiling** is already reached. Counts `worker: "pi"` only, and says so: `dispatch.sh` is the only thing that writes records today, so the Sonnet half of "2 Pi + 2 Sonnet" is unenforceable rather than silently enforced. | `--force`, or `DISPATCH_PI_CEILING=<n>` for a session |
| `5` | The worker's model API gave **no HTTP response** (see the preflight below). | `--no-preflight` |
| `6` | `--wait` only: the worker is gone and its record never closed, or the record closed with no exit code — the worker's fate is unknown (exit 1 is a worker's own code, so it is not reused here). | — |

**The two overrides are deliberately separate flags.** The ceiling is a
calibration guess (ADR 0086; task 031 sets the real number), so `--force` is a
reasonable thing to reach for. The worktree rule protects against losing work,
so `--force` must not silently switch it off as a side effect of raising the
ceiling. Each prints a loud warning naming the rule it bypassed.

Records gained a `worktree` field for this. A record written before that
(no field) blocks the shared-checkout check rather than passing it — it cannot
prove it is running somewhere else, and the conservative reading is the safe one
for the rule whose failure mode is two agents writing one checkout.

A dispatch record normally closes even when its worker dies, and
`orchestrator-count.sh` skips closed records — so **a non-zero `exit_code` on a
finished record is a crash signal**, and the place a worker that exited non-zero
is visible unless someone ran `dispatch.sh --wait`, which returns the same code
to its caller. When the record *never* closes (the launching subshell was killed,
or its closing write failed) the signal is the other shape: `finished: null`
with a dead pid, which `orchestrator-count.sh` reports as overdue/DEAD once past
the deadline (when the deadline is readable), and which `--wait` exits 6 on.

Covered by `tests/dispatch.test.sh` (stubbed `ask-pi`, real git worktrees, no Pi
call).

### Waiting, the brief file, and the preflight

**Without `--wait`, `dispatch.sh` returns at once** — the record path on stdout
line 1 and the worker pid on line 2, while `ask-pi` keeps running in the
background. Redirect stdout to a **file, never a pipe**: the detached worker
subshell inherits the caller's stdout, so a caller reading a pipe stays blocked
until the worker exits (and killing that caller kills the worker). That is an
accident of inheritance, not a wait.

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

## Starting and landing a ticket (`ticket.sh`)

One command starts a build ticket and one lands it (task 292). Both read the same
`.claude/dispatch/` records `dispatch.sh` writes in the main checkout and the same lane
registry `lane` writes, so nothing is pasted between windows.

```bash
tools/agent-bridge/ticket.sh start --series <s> --task <NNN-slug> \
    --owns <paths> --eta <minutes> --brief <file> [--wait]
tools/agent-bridge/ticket.sh land <pr> --reviewed <sha> \
    --fail-first "<command>" [--read-unreviewed] [--dry-run]
```

`start` refuses a task `frontier-ready.sh --branch build/<s> --series <s>` does not name, cuts
`ticket/<s>-<NNN>` from the tip of `build/<s>` with no upstream, claims the Pi lane (its
worktree is created by `lane new --worktree`) with the ticket's `tasks/inbox/` and
`tasks/done/` files added to the owned paths, then dispatches from that worktree with
`--message-file`. It prints the lane, branch, worktree and record paths. Without `--wait` it
returns once the worker is launched; with `--wait` it passes the flag through and exits with
the worker's code.

`land` runs the five mechanical steps of `tasks/README.md` §The lander check in order and
stops at the first that fails, naming it: (1) the ticket worktree is at the PR's head and every
path in `git diff <base>...<head>` is under the lane's owned paths; (2)
`tools/agent-bridge/tests/run-all.sh` passes on the ticket worktree; (3) the PR body's
`## Review` section's last un-negated verdict token is not RED (so a recorded round-1 RED
before a final YELLOW does not refuse, but a section that ends on RED does); (4) `--fail-first` is present (recorded, never judged); (5)
`git diff <reviewed>..<head>` is printed and a non-empty diff needs `--read-unreviewed`. It
refuses when the `build/<s>` worktree is missing or not on `build/<s>`, the ticket worktree has
uncommitted files, or a dispatch for the lane is still running. Then it calls `merge-pr.sh
<pr>`, fast-forwards the local `build/<s>` from `origin`, releases the lane, removes the
worktree, deletes the ticket branch locally and on origin, and appends one tab-separated line
to `.claude/dispatch/lands.tsv`: date, series, task, PR, reviewed sha, head sha, the lane's
summed worker seconds, and the fail-first command. Once the PR has merged the row is written
even if a removal step fails, and the failures are named. `--dry-run` prints the unreviewed
diff and the mutation steps without running the tests or changing anything.

Tests: `tests/ticket.test.sh` (a throwaway repo with a stub `gh` and a stub `ask-pi`, real
worktrees).

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
| **Writing in a held tree** | Refused (exit 2) by the `lane-guard pre` hook on every `Edit`/`Write`/`MultiEdit`/`NotebookEdit` and write-looking `Bash` command. | Hold a lane claim on the tree (each side's own `--share-worktree` claim lets both write), or be the holder, or be the only live session there. |

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
- **Who holds a tree when there is no claim (task 154).** `lane-guard pre` resolves the holder as
  (a) a live, non-review lane claim on the tree — its claimant holds it; (b) with no such claim,
  the **earliest `startedAt`** live Claude session whose `cwd` is in the tree. A session file with
  no `startedAt` counts as latest-started (never the earliest holder); if none in the tree has
  one, there is no `startedAt` holder and the write is allowed. The tiebreak is what makes two
  co-tenant sessions non-symmetric: exactly one of them is the holder.
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

## Pruning dead lanes (`lane prune`) — task 295

`lane ls` shows a `STATE` for every lane: `live`, `STALE` (a Claude lane whose session is gone),
and `unknown` (a Pi lane — Pi writes no session file the bridge can check). `lane prune` lists the
lanes nobody holds and, with `--apply`, removes their registry rows.

```bash
lane prune            # list what would be pruned, and why
lane prune --all      # also list the lanes it keeps, and why
lane prune --apply    # remove exactly the listed registry rows
```

A lane is listed **only when its session is not live** and one of these holds:

| Condition | `STALE` (Claude) | Pi (`unknown`, or `--agent pi`) |
|---|---|---|
| branch tip is an ancestor of `origin/main` as last fetched, and its linked worktree is clean | listed | **kept** — its liveness cannot be observed, so a merged branch alone is not enough |
| branch no longer exists | listed | listed |
| worktree folder is missing | listed | listed |

- **A live lane is never listed**, whatever its branch or worktree says.
- **A branch that IS the repository's default branch is never called merged** — a branch is
trivially merged into itself. The default branch is read from `origin/HEAD` (falling back to
`main` when that is unset), and local `main` is always exempt too: the command compares against
`origin/main` by contract, so `origin/HEAD` naming another branch must not turn the one real
`main` lane into "merged".
- **The Pi rule follows the agent, not just the state.** A `--agent pi` row whose claimant is a
Claude session that has since died reads `STALE`, but the backgrounded Pi worker may still be
running — so the conservative rule (`unknown` **or** `--agent pi`) applies to it too.
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
