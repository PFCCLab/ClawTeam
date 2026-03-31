# ClawTeam CLI Complete Reference

## Global Options

```
clawteam [--version] [--json] [--data-dir PATH] <command>
```

- `--json` — Output JSON instead of human-readable text. Apply before subcommand: `clawteam --json team discover`
- `--data-dir PATH` — Override data directory (default: `~/.clawteam`)

## Environment Variables

ClawTeam agents use these environment variables for identity:

| Variable | Description | Example |
|----------|-------------|---------|
| `CLAWTEAM_AGENT_ID` | Unique agent identifier | `a1b2c3d4e5f6` |
| `CLAWTEAM_AGENT_NAME` | Human-readable agent name | `alice` |
| `CLAWTEAM_AGENT_TYPE` | Agent role type | `leader`, `general-purpose`, `researcher` |
| `CLAWTEAM_TEAM_NAME` | Team the agent belongs to | `dev-team` |
| `CLAWTEAM_DATA_DIR` | Override data directory | `/tmp/clawteam-data` |

When spawning agents via `clawteam spawn`, these are set automatically.

---

## Team Commands (`clawteam team`)

### `team spawn-team`

Create a new team and register the leader.

```bash
clawteam team spawn-team <name> [options]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--description, -d` | Team description | `""` |
| `--agent-name, -n` | Leader agent name | `"leader"` |
| `--agent-type` | Leader agent type | `"leader"` |

Example:
```bash
clawteam team spawn-team dev-team -d "Backend development team" -n alice
```

### `team discover`

List all existing teams.

```bash
clawteam team discover
clawteam --json team discover
```

Returns: name, description, leadAgentId, memberCount for each team.

### `team status`

Show team configuration and member list.

```bash
clawteam team status <team>
```

### `team request-join`

Request to join a team. Blocks until leader approves/rejects or timeout.

```bash
clawteam team request-join <team> <proposed-name> [options]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--capabilities, -c` | Agent capabilities description | `""` |
| `--timeout, -t` | Timeout in seconds | `60` |

### `team approve-join`

Approve a pending join request (leader only).

```bash
clawteam team approve-join <team> <request-id> [--assigned-name NAME]
```

### `team reject-join`

Reject a pending join request (leader only).

```bash
clawteam team reject-join <team> <request-id> [--reason TEXT]
```

### `team cleanup`

Delete a team and all its data (config, inboxes, tasks).

```bash
clawteam team cleanup <team> [--force]
```

---

## Inbox Commands (`clawteam inbox`)

### `inbox send`

Send a point-to-point message to an agent.

```bash
clawteam inbox send <team> <to> <content> [options]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--key, -k` | Routing key | `None` |
| `--type` | Message type | `"message"` |

### `inbox broadcast`

Broadcast a message to all team members (except sender).

```bash
clawteam inbox broadcast <team> <content> [options]
```

### `inbox receive`

Receive and consume messages from inbox (destructive — messages are deleted).

```bash
clawteam inbox receive <team> [options]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--agent, -a` | Agent name (default: from env) | env |
| `--limit, -l` | Max messages to receive | `10` |

### `inbox peek`

Peek at messages without consuming them (non-destructive).

```bash
clawteam inbox peek <team> [--agent NAME]
```

### `inbox watch`

Watch inbox for new messages in real-time (blocking, Ctrl+C to stop).

```bash
clawteam inbox watch <team> [--agent NAME] [--poll-interval 1.0]
```

---

## Task Commands (`clawteam task`)

### `task create`

Create a new task.

```bash
clawteam task create <team> <subject> [options]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--description, -d` | Task description | `""` |
| `--owner, -o` | Owner agent name | `""` |
| `--priority, -p` | Task priority: `low`, `medium`, `high`, `urgent` | `"medium"` |
| `--blocks` | Comma-separated task IDs this blocks | `None` |
| `--blocked-by` | Comma-separated task IDs blocking this | `None` |

Example:
```bash
clawteam task create dev-team "Implement auth" -o alice -d "Add JWT authentication"
```

### `task get`

Get a single task by ID.

```bash
clawteam task get <team> <task-id>
```

### `task update`

Update a task's status, owner, or dependencies.

```bash
clawteam task update <team> <task-id> [options]
```

| Option | Description |
|--------|-------------|
| `--status, -s` | New status: `pending`, `in_progress`, `completed`, `blocked` |
| `--owner, -o` | New owner |
| `--subject` | New subject |
| `--description, -d` | New description |
| `--priority, -p` | New priority: `low`, `medium`, `high`, `urgent` |
| `--add-blocks` | Comma-separated task IDs to add to blocks |
| `--add-blocked-by` | Comma-separated task IDs to add to blocked-by |
| `--force, -f` | Force override task lock |

When a task is marked `completed`, any tasks blocked by it are automatically unblocked (moved from `blocked` to `pending` if no other blockers remain).

### `task list`

List all tasks for a team, with optional filters.

```bash
clawteam task list <team> [--status STATUS] [--owner NAME] [--priority LEVEL] [--sort-priority]
```

---

## Board Commands (`clawteam board`)

### `board show`

Show detailed team board data. Human output renders the kanban board; JSON output also includes
members with inbox identity fields plus persistent message history from the event log.

```bash
clawteam board show <team>
clawteam --json board show <team>
```

Recent board payloads include member-aware message aliases such as `memberKey`, `inboxName`,
`fromLabel`, and `toLabel`, which are used by the browser board to filter inbox history.

### `board overview`

Show summary of all teams in a table.

```bash
clawteam board overview
clawteam --json board overview
```

### `board live`

Live-refreshing kanban board. Auto-refreshes at interval. Ctrl+C to stop.

```bash
clawteam board live <team> [--interval 2.0]
```

---

## Plan Commands (`clawteam plan`)

### `plan submit`

Submit a plan for leader approval. Content can be inline text or a file path.

```bash
clawteam plan submit <team> <agent> <plan-content-or-file> [--summary TEXT]
```

### `plan approve`

Approve a submitted plan.

```bash
clawteam plan approve <team> <plan-id> <agent> [--feedback TEXT]
```

### `plan reject`

Reject a submitted plan.

```bash
clawteam plan reject <team> <plan-id> <agent> [--feedback TEXT]
```

---

## Lifecycle Commands (`clawteam lifecycle`)

### `lifecycle request-shutdown`

Request an agent to shut down.

```bash
clawteam lifecycle request-shutdown <team> <from-agent> <to-agent> [--reason TEXT]
```

### `lifecycle approve-shutdown`

Agent agrees to shut down.

```bash
clawteam lifecycle approve-shutdown <team> <request-id> <agent>
```

### `lifecycle reject-shutdown`

Agent rejects shutdown request.

```bash
clawteam lifecycle reject-shutdown <team> <request-id> <agent> [--reason TEXT]
```

### `lifecycle idle`

Send idle notification to leader (agent has no more work).

```bash
clawteam lifecycle idle <team> [--last-task ID] [--task-status STATUS]
```

---

## Spawn Command

Spawn a new agent process with team environment variables.

```bash
clawteam spawn [backend] [command...] [options]
```

| Option | Description | Default |
|--------|-------------|---------|
| `backend` | Backend: `tmux` (default), `subprocess`, or `http` | `tmux` |
| `command` | Command and arguments to run | `claude` |
| `--team, -t` | Team name | `"default"` |
| `--agent-name, -n` | Agent name | auto-generated |
| `--agent-type` | Agent type | `"general-purpose"` |
| `--task` | Task text for agent's initial prompt (literal text, not a task ID lookup) | `None` |
| `--profile` | Apply a named runtime profile | `None` |
| `--workspace / --no-workspace, -w` | Create isolated git worktree | `auto` |
| `--repo` | Git repo path | cwd |
| `--skip-permissions / --no-skip-permissions` | Skip tool approval for claude | from config (true) |
| `--resume, -r` | Resume previous session if available | `false` |
| `--replace` | Stop existing agent with same name before spawning | `false` |
| `--skill` | Skill name(s) to inject into system prompt (repeatable, claude only) | `None` |
| `--node` | Remote daemon URL or named node alias — spawns agent on remote machine via HTTP | `None` |

Backends: `tmux` (visual tmux windows), `subprocess` (background processes), `http` (remote daemon).

`--node` implies `http` backend automatically. Accepts a full URL or a named node alias configured via `clawteam node set`.

Example:
```bash
# Local spawn (default)
clawteam spawn --team dev-team --agent-name bob --task "Implement auth"

# Remote spawn via daemon
clawteam spawn --team dev-team --agent-name bob \
  --node http://10.0.0.5:9090 --task "Implement auth"

# Remote, no worktree, replace existing
clawteam spawn --team dev-team --agent-name bob \
  --node http://10.0.0.5:9090 --no-workspace --replace --task "New task"

# Local with explicit backend and command
clawteam spawn subprocess claude --team dev-team --agent-name bob --agent-type researcher
```

---

## Node Commands (`clawteam node`)

Manage named aliases for remote daemon nodes. Aliases let you use `--node XPU` instead of `--node http://10.129.16.114:8181`.

### `node list`

List all configured node aliases.

```bash
clawteam node list
clawteam --json node list
```

### `node show`

Show a single node alias configuration.

```bash
clawteam node show <name>
```

### `node set`

Create or update a node alias.

```bash
clawteam node set <name> --url <url> [--token TOKEN] [--description TEXT]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--url` | Daemon URL (e.g. `http://10.0.0.5:9090`) | required |
| `--token` | Bearer token (overrides `daemon_token`) | `""` |
| `--description, -d` | Human-readable description | `""` |

Example:
```bash
clawteam node set XPU --url http://10.129.16.114:8181 -d "XPU dev machine"
clawteam node set GPU --url http://10.0.0.5:9090 --token mysecret -d "GPU training box"
```

### `node remove`

Remove a node alias.

```bash
clawteam node remove <name>
```

---

## Daemon

The daemon runs on a remote machine to accept agent spawn/stop requests and serve file sync.

### Starting the Daemon

```bash
python -c "from clawteam.daemon.server import serve; serve()"                            # defaults: 0.0.0.0:9090, no auth
python -c "from clawteam.daemon.server import serve; serve(port=8181, token='secret', repo_root='/path/to/repo')"
```

Or equivalently in a Python script:
```python
from clawteam.daemon.server import serve
serve(port=9090, token="mysecret", repo_root="/path/to/repo")
```

### Configuration

| Config field | Env var | Default | Description |
|-------------|---------|---------|-------------|
| `daemon_token` | `CLAWTEAM_DAEMON_TOKEN` | `""` | Bearer token (empty = no auth) |
| `daemon_port` | `CLAWTEAM_DAEMON_PORT` | `9090` | HTTP listen port |
| `sync_interval` | — | `5.0` | File sync polling interval (seconds) |

### Daemon API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/healthz` | No | Health check |
| `GET` | `/agents?team=<team>` | Yes | List agents with liveness status |
| `GET` | `/status/<agent>?team=<team>` | Yes | Check specific agent liveness |
| `POST` | `/spawn` | Yes | Spawn agent (JSON body) |
| `POST` | `/stop/<agent>?team=<team>` | Yes | Stop a running agent |
| `GET` | `/sync/manifest?team=<team>` | Yes | Get file manifest for sync |
| `POST` | `/sync/pull` | Yes | Pull file contents (batch, base64) |
| `POST` | `/sync/push` | Yes | Push file contents (batch, base64) |

### File Sync

Sync keeps local and remote `data_dir` in sync bidirectionally. Synced file patterns:

| Directory | Files |
|-----------|-------|
| `tasks/{team}/` | `task-*.json` |
| `teams/{team}/inboxes/*/` | `msg-*.json` |
| `teams/{team}/` | `config.json`, `spawn_registry.json` |
| `teams/{team}/events/` | `evt-*.json` |
| `sessions/{team}/` | `*.json` |
| `costs/{team}/` | `cost-*.json` |
| `plans/{team}/` | `*.md` |
| `teams/{team}/peers/` | `*.json` |

Conflict resolution strategy:
- **Tasks** (`task-*.json`): last-write-wins (compares `updatedAt` timestamp)
- **Config/registry**: leader wins (always push)
- **Sessions/plans**: remote wins (pull, agent-owned files)
- **Other** (messages, events, costs): remote wins (pull)

---

## Identity Commands (`clawteam identity`)

### `identity show`

Show current agent identity from environment variables.

```bash
clawteam identity show
```

### `identity set`

Print shell export commands to set identity environment variables.

```bash
eval $(clawteam identity set --agent-name alice --team dev-team)
```

---

## Data Model

### Task Statuses

| Status | Description |
|--------|-------------|
| `pending` | Not yet started |
| `in_progress` | Currently being worked on |
| `completed` | Done (auto-unblocks dependents) |
| `blocked` | Waiting on other tasks |

### Message Types

| Type | Description |
|------|-------------|
| `message` | General point-to-point message |
| `broadcast` | Broadcast to all members |
| `join_request` | Request to join team |
| `join_approved` / `join_rejected` | Join response |
| `plan_approval_request` | Plan submitted for review |
| `plan_approved` / `plan_rejected` | Plan response |
| `shutdown_request` | Shutdown request |
| `shutdown_approved` / `shutdown_rejected` | Shutdown response |
| `idle` | Agent idle notification |

### File Storage Layout

```
~/.clawteam/
├── teams/{team}/
│   ├── config.json          # TeamConfig (name, members, leader)
│   └── inboxes/{agent}/     # msg-{timestamp}-{uuid}.json files
├── tasks/{team}/
│   └── task-{id}.json       # Individual task files
└── plans/
    └── {agent}-{id}.md      # Plan documents
```
