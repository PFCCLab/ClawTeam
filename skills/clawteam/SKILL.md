---
name: ClawTeam Multi-Agent Coordination
description: >
  This skill should be used when the user asks to "create a team", "spawn agents",
  "assign tasks", "coordinate multiple agents", "check team status", "view kanban board",
  "send messages between agents", "manage team tasks", "monitor team progress",
  or mentions "clawteam", "multi-agent coordination", "team collaboration",
  "agent inbox", "task board", "spawn worker". This skill should also be triggered
  when the current task is complex enough to benefit from splitting into subtasks
  and delegating to multiple agents — for example when the user asks to "build a
  full-stack app", "refactor the entire codebase", "implement multiple features
  in parallel", or when the agent determines that the work scope exceeds what a
  single agent can efficiently handle alone. Provides comprehensive guidance for
  using the ClawTeam CLI to orchestrate multi-agent teams with task management,
  messaging, monitoring, runtime profiles, git context, and recovery tooling.
version: 0.3.1
---

# ClawTeam Multi-Agent Coordination

ClawTeam is a framework-agnostic CLI tool for coordinating multiple AI agents as a team.
It provides team/task management, inter-agent messaging, git worktree isolation, provider-aware
runtime profiles, git context injection, snapshots, and terminal-based monitoring dashboards.

All operations are performed via the `clawteam` CLI. Data is stored in `~/.clawteam/` by default.

## Installation

```bash
pip install clawteam
```

Requires Python 3.10+. For P2P transport support: `pip install clawteam[p2p]`.

## Prerequisites

- `tmux` installed (default spawn backend)
- A CLI coding agent such as `claude`, `codex`, `gemini`, `kimi`, `nanobot`, or `openclaw`
- A git repository for worktree isolation and context features
- Default dependencies installed if you want the TUI wizard (`clawteam profile wizard`)

## Core Concepts

**Teams** — Named groups of agents with one leader and zero or more workers.

**Inbox** — File-based message queue per agent. `receive` is destructive; `peek` is not.

**Tasks** — Shared task board with `pending`, `in_progress`, `completed`, and `blocked`.
Tasks support dependency chains and priorities.

**Profiles** — Reusable client/provider/runtime configs used by `spawn` and `launch`.

**Presets** — Shared provider templates used to generate one or more profiles.

**Context** — Git/worktree-aware context tools for overlap checks, recent changes, and prompt injection.

**Board** — Team dashboard with kanban tasks, inbox counts, and message history views, plus gource activity visualization.

**Daemon** — Remote agent host. Runs on a target machine and accepts spawn/stop/sync requests over HTTP.
Start with `python -c "from clawteam.daemon.server import serve; serve()"` (default port 9090).

**Sync** — File-based bidirectional sync between local and remote data directories.
Uses three-way merge with last-write-wins for task conflicts. Syncs tasks, inboxes, sessions,
plans, costs, events, config, and peer info.

## Quick Start

### Set Up a Team with Tasks

```bash
export CLAWTEAM_AGENT_ID="leader-001"
export CLAWTEAM_AGENT_NAME="leader"
export CLAWTEAM_AGENT_TYPE="leader"

clawteam team spawn-team my-team -d "Project team" -n leader
clawteam task create my-team "Design system" -o leader
clawteam task create my-team "Implement feature" -o worker1
clawteam task create my-team "Write tests" -o worker2
clawteam board show my-team
```

### Configure Runtime Profiles

```bash
# Inspect built-in provider templates
clawteam preset list
clawteam preset show moonshot-cn

# Generate a reusable profile from a preset
clawteam preset generate-profile moonshot-cn claude --name claude-kimi

# Or use the interactive TUI
clawteam profile wizard

# Claude Code on a fresh machine/home may need onboarding repair once
clawteam profile doctor claude

# Smoke-test the profile before using it in a team
MOONSHOT_API_KEY=... clawteam profile test claude-kimi
```

### Spawn and Coordinate Agents

```bash
# Default path: tmux backend, claude command, git worktree isolation, skip-permissions on
clawteam spawn --team my-team --agent-name worker1 --task "Implement the auth module"
clawteam spawn --team my-team --agent-name worker2 --task "Write unit tests"

# Explicit backend and command
clawteam spawn tmux claude --team my-team --agent-name worker3 --task "Build API endpoints"
clawteam spawn subprocess claude --team my-team --agent-name worker4 --task "Run linting"

# Recommended for non-default providers/models
clawteam spawn tmux --profile claude-kimi --team my-team --agent-name worker5 --task "Build API endpoints"
clawteam spawn subprocess --profile gemini-vertex --team my-team --agent-name worker6 --task "Run linting"

clawteam board attach my-team
clawteam inbox send my-team worker1 "Start implementing the auth module"
clawteam board live my-team --interval 3

# Remote agent — spawn on a remote daemon (--node implies http backend)
clawteam spawn --team my-team --agent-name worker-remote \
  --node http://remote-host:9090 --task "Build API endpoints"

# Remote using a named node alias (configured with `clawteam node set`)
clawteam spawn --team my-team --agent-name worker-remote \
  --node XPU --task "Build API endpoints"

# Remote without git worktree
clawteam spawn --team my-team --agent-name worker-remote \
  --node XPU --no-workspace --task "Run linting"

# Replace a running remote agent with a new task
clawteam spawn --team my-team --agent-name worker-remote \
  --node XPU --replace --task "New assignment"
```

### Spawn Defaults

| Setting | Default | Override |
|---------|---------|----------|
| Backend | `tmux` | `clawteam spawn subprocess ...` or `--node` for `http` |
| Command | `claude` | `clawteam spawn tmux my-cmd ...` |
| Workspace | `auto` (git worktree) | `--no-workspace` or config `workspace=never` |
| Permissions | skip | `--no-skip-permissions` or config `skip_permissions=false` |
| Runtime profile | none | `--profile <name>` |
| Node (remote) | none (local) | `--node <alias>` or `--node http://host:9090` |
| Replace | `false` | `--replace` (stop existing agent with same name first) |

Use `--profile` whenever you need a non-default provider, model, endpoint, or auth mapping.

### Task Lifecycle

```bash
# Create with dependencies
clawteam task create my-team "Deploy" --blocked-by <impl-task-id>,<test-task-id>

# Create with priority
clawteam task create my-team "Hotfix prod issue" --priority high

# Update status
clawteam task update my-team <task-id> --status in_progress
clawteam task update my-team <task-id> --status completed

# Filter tasks
clawteam task list my-team --status blocked
clawteam task list my-team --owner worker1
clawteam task list my-team --priority high
```

### Waiting for Sub-Agents

```bash
clawteam task wait my-team
clawteam task wait my-team --timeout 300 --poll-interval 10
clawteam task wait my-team --agent coordinator
clawteam --json task wait my-team --timeout 600
```

### Worker Loop Protocol

Workers should not stop after completing the initial `--task`. The expected loop is:

```bash
# 1. Check tasks assigned to you
clawteam task list my-team --owner worker1

# 2. Finish any pending work, then check for new instructions
clawteam inbox receive my-team --agent worker1

# 3. If idle, notify the leader and keep monitoring for follow-ups
clawteam lifecycle idle my-team
```

Repeat the loop until the leader explicitly shuts the worker down.

### Git Context and Conflict Checks

```bash
clawteam context log my-team
clawteam context conflicts my-team
clawteam context inject my-team --agent worker1
```

Use these before reassigning work, continuing another worker's task, or merging overlapping changes.

### Snapshots and Recovery

```bash
clawteam team snapshot my-team --tag before-refactor
clawteam team snapshots my-team
clawteam team restore my-team --snapshot before-refactor
```

### Activity Visualization

```bash
clawteam board gource my-team --log-only
clawteam board gource my-team --live
```

Prefer `--log-only` in headless environments.

## Supported CLI Agents

Common validated CLIs include:
- `claude`
- `codex`
- `gemini`
- `kimi`
- `nanobot`
- `openclaw`

OpenClaw worker spawns are normalized automatically. Bare `openclaw` commands are promoted to
the agent entrypoint and wired with `--local`, `--session-id`, and `--message` as needed.

Configure non-default providers through `profile` + `preset` instead of hardcoding env vars into prompts.

## Command Groups

| Group | Purpose | Key Commands |
|-------|---------|-------------|
| `preset` | Shared provider templates | `list`, `show`, `generate-profile`, `bootstrap` |
| `profile` | Reusable client/provider configs | `list`, `show`, `set`, `test`, `wizard`, `doctor` |
| `node` | Remote daemon node aliases | `list`, `show`, `set`, `remove` |
| `team` | Team lifecycle | `spawn-team`, `discover`, `status`, `request-join`, `approve-join`, `cleanup`, `snapshot`, `restore` |
| `inbox` | Messaging | `send`, `broadcast`, `receive`, `peek`, `watch` |
| `task` | Task management | `create`, `get`, `update`, `list`, `wait` |
| `board` | Monitoring and visualization | `show`, `overview`, `live`, `attach`, `serve`, `gource` |
| `context` | Git/worktree context | `diff`, `files`, `conflicts`, `log`, `inject` |
| `plan` | Plan approval | `submit`, `approve`, `reject` |
| `lifecycle` | Agent lifecycle | `request-shutdown`, `approve-shutdown`, `idle` |
| `spawn` | Process spawning (local or remote) | `spawn [backend] [command]` |
| `daemon` | Remote agent host | `python -m clawteam.daemon.server` |
| `identity` | Identity management | `show`, `set` |

## JSON Output

All commands support `--json` for machine-readable output. Put the flag before the subcommand:

```bash
clawteam --json team discover
clawteam --json board show my-team
clawteam --json task list my-team --status pending
```

## Important Notes

- `inbox receive` consumes messages. Use `inbox peek` for non-destructive reads.
- Task status `blocked` is auto-set when `--blocked-by` is specified at creation.
- Completing a task auto-unblocks tasks that list it in `blockedBy`.
- Tasks also support `priority`; use `high` for urgent unblockers and production fixes.
- Workers are expected to keep polling tasks/inbox after the first task instead of exiting immediately.
- `clawteam spawn` defaults to tmux, git worktree isolation, and skip-permissions.
- `clawteam launch` also respects `skip_permissions`, so template workers no longer stall on approval prompts.
- All file writes use atomic tmp+rename to prevent corruption.
- Identity env vars are set automatically when spawning via `clawteam spawn`.
- Use `board attach <team>` to watch all agents in a tiled tmux layout.
- `board show` JSON and the browser board now include message history with member-aware aliases, which is useful for inbox triage and handoffs.
- Prefer `--profile` for non-default providers/models instead of manually exporting provider env vars.
- `profile` is the final runtime object; `preset` is a reusable template for generating profiles.
- For Claude Code on a fresh machine/home, run `clawteam profile doctor claude` once before spawning.
- `context inject` and `context conflicts` are the recommended way to hand off cross-worktree tasks safely.
- `--node URL` implies `http` backend; the daemon on that URL runs the agent remotely.
- `--node` also accepts a named alias configured via `clawteam node set`; use `clawteam node list` to see available aliases.
- Remote agents need the daemon started on the target machine (`from clawteam.daemon.server import serve; serve()`, default port 9090).
- Sync uses last-write-wins conflict resolution for tasks; config/registry uses leader-wins.
- `--task` passes literal text into the agent prompt — it is NOT a task store lookup. Use full task IDs so agents can call `task get`.
- `--blocked-by` requires full 8-char hex task IDs. Numeric indexes or arbitrary strings create unresolvable dependencies.
- Remote agents cannot use `workspace *`, `context *`, `board attach`, or `board gource` (require local git/tmux).
- `team cleanup --force` sends HTTP `/stop/{agent}` to terminate remote agents on the daemon.

## Additional Resources

- **`references/cli-reference.md`** — Complete CLI reference with commands, options, and data models
- **`references/workflows.md`** — Multi-agent workflows: setup, spawn coordination, join protocol, plan approval, graceful shutdown, monitoring patterns
