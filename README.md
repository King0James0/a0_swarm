# A0 Swarm

Spawn parallel subagents and monitor / message them from a sidebar panel.

See `docs/superpowers/specs/2026-05-14-a0-swarm-design.md` for the original
design and `docs/superpowers/specs/2026-05-15-a0-swarm-communication-observability-design.md`
for the communication, observability, and remote-container enhancement spec.

## Tools

- `delegate_parallel(tasks=[{label, task, profile?, endpoint?}, ...])` — runs local or remote subagents concurrently under one swarm run.
- `swarm_message(recipient, content, is_blocker?)` — records a run-scoped ledger message and attempts delivery to the orchestrator or a peer in the same swarm run.

## Subagent workspace (where local subs work)

By default a delegated sub runs in the global workdir, so it can't see the repo the orchestrator
is working in, and all subs share one folder. The `subagent_workspace` setting (Plugin Settings →
Agent, or `default_config.yaml`) controls this:

| Mode | Each sub gets | Use for |
|---|---|---|
| `none` (default) | the global workdir (unchanged) | back-compat / no project context |
| `inherit` | the parent's active project activated (shared folder) | parallel **read / analysis** |
| `isolated` | its **own git worktree + branch** of the parent's repo, registered as a project | parallel **editing** without collision |

`inherit` only makes subs *see* the repo — they still share one working tree, so it is **not** safe
for parallel edits. Use `isolated` when subs will modify files: each sub gets a separate worktree on
its own `swarm/<key>` branch off the parent's current commit (subs start clean from `HEAD`;
uncommitted changes in the parent are not carried), so their edits and git operations can't clobber
each other. Worktrees are reclaimed when each sub finishes (and a crash-safe sweep reclaims any left
by a crashed run).

`isolated` requires the parent to have an **active project that is a git repo**; otherwise it falls
back to `inherit`. If the [`a0_worktree`](https://github.com/King0James0/a0-worktree) plugin is
installed it owns worktree lifecycle and swarm delegates to it; otherwise swarm manages an inline
worktree itself. Either way swarm only ever touches worktrees it created (marker-scoped), so it
coexists safely with other worktree plugins or manual `git worktree` use.

## Delivery states

- `queued` — accepted into the ledger and visible in the panel.
- `delivered` — injected into the target local context or accepted by the remote A2A endpoint.
- `failed` — delivery was attempted and rejected; the panel shows the reason and retry action.

`sent` in the UI means the ledger accepted the message. It does not imply delivery until the state changes to `delivered`.

## Remote setup

Configure remotes in Plugin Settings. The primary path is A2A Discovery: paste a remote A2A URL, test its Agent Card, review advertised skills / communication support, then add it as a remote. Same-host Docker discovery remains optional and can list likely Agent Zero containers when Docker is available. If Docker access is missing, Remote Diagnostics shows a Docker Access Setup card with copy-ready Compose, `docker run`, and restart snippets plus macOS Docker Desktop steps.

Use the Test action before assigning work to a remote endpoint. The test checks agent-card reachability and authentication, then reports whether continuation and cancellation are available. Stored remote auth tokens are used for follow-up messages and cancellation, but are not exposed in status snapshots.

## UI

Mounts at `sidebar-bottom-wrapper-end`. Live updates over the existing
`WsWebui` socket. Per-agent: status icon, current activity, blocker chip,
message thread, Message / Send & Unblock / Cancel actions, plus a Clear
Completed button.

## API

| Endpoint | Method | Body | Returns |
|---|---|---|---|
| `/api/plugins/a0_swarm/swarm_status` | POST | `{parent_context_id?}` | `{runs: SwarmRun[], agents: SwarmAgent[]}` |
| `/api/plugins/a0_swarm/swarm_send_message` | POST | `{agent_name, content, unblock?}` | `{ok, message_id, delivery_state}` |
| `/api/plugins/a0_swarm/swarm_retry_message` | POST | `{message_id}` | `{ok, message_id, delivery_state}` |
| `/api/plugins/a0_swarm/swarm_cancel` | POST | `{agent_name}` | `{ok}` |
| `/api/plugins/a0_swarm/swarm_clear_completed` | POST | `{parent_context_id?}` | `{ok}` |
| `/api/plugins/a0_swarm/swarm_test_remote` | POST | `{label?, url?, auth_token?}` | `{ok, checks, discovery, remote}` |
| `/api/plugins/a0_swarm/swarm_discover_docker` | POST | `{}` | `{ok, candidates}` |

## Tests

```bash
pytest tests/test_a0_swarm_registry.py tests/test_a0_swarm_delegate.py \
       tests/test_a0_swarm_message_tool.py tests/test_a0_swarm_api.py \
       tests/test_a0_swarm_extensions.py tests/test_a0_swarm_delivery.py \
       tests/test_a0_swarm_remote_setup.py -v
```

## Source location

`usr/` is gitignored by default; this plugin's source is force-tracked for
in-repo development. End-user installs clone into their own `usr/plugins/`.
