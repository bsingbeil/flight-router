# agent-bridge

Three commands that let Claude Code and Pi work together without Brendan
relaying messages between them.

| Command | Does |
|---|---|
| `ask-pi "<msg>"` | Claude Code → Pi. Pi's reply prints on stdout, straight into the caller's context. |
| `ask-claude "<msg>"` | Pi → Claude Code. Claude answers with read-only tools — it reviews, Pi edits. |
| `lane new <name> --owns <path>` | Claims a session id + owned paths (optionally its own worktree) and prints a paste-ready coordinates block for a second terminal window. |

Both `ask-*` commands accept piped stdin (`git diff | ask-pi "review this"`),
take `-t <thread>` for parallel conversations, and are threaded per git repo
root so no context bleeds between projects. A depth guard stops the two agents
ping-ponging past 2 hops.

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
