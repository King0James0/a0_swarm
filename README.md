# A0 Swarm

Spawn parallel subagents and monitor / message them from a sidebar panel.

See `docs/superpowers/specs/2026-05-14-a0-swarm-design.md` for the original
design and `docs/superpowers/specs/2026-05-15-a0-swarm-communication-observability-design.md`
for the communication, observability, and remote-container enhancement spec.

## Tools

- `delegate_parallel(tasks=[{label, task, profile?, endpoint?}, ...])` — runs local or remote subagents concurrently under one swarm run.
- `swarm_message(recipient, content, is_blocker?)` — records a run-scoped ledger message and attempts delivery to the orchestrator or a peer in the same swarm run.

## Subagent workspace (where local subs work)

Local subagents spawned by `delegate_parallel` need somewhere to work. The `subagent_workspace`
setting controls that. Quick reference:

| Mode | Each sub gets | Use for |
|---|---|---|
| `none` (default) | the global workdir (today's behavior) | back-compat / no project context |
| `inherit` | the orchestrator's active project (shared folder) | parallel **read / analysis** |
| `isolated` | its **own git worktree + branch** of the orchestrator's repo | parallel **editing** without collision |

### `none` (default) — every sub runs in the global workdir

| Scenario | What happens to subs |
|---|---|
| `none` + no project | All subs run in the global workdir (`/a0/usr/workdir`), sharing one folder |
| `none` + orchestrator has a project | Subs **still** run in the global workdir — they ignore the project |

So with `none`:

- Every local sub runs in the one global workdir, regardless of whether the orchestrator is in a project.
- **No project inheritance** — subs never see the orchestrator's repo.
- **No isolation** — all subs share that single folder, so two subs writing the same path would collide.

This is the default and matches the plugin's original behavior.

### `inherit` — subs share the orchestrator's project

| Scenario | What happens to subs |
|---|---|
| `inherit` + no project | Falls back to the global workdir (nothing to inherit) |
| `inherit` + orchestrator has a project | Each sub gets that **same** project activated → all run in the project folder and see the repo |

So with `inherit`:

- Subs now **see the orchestrator's repo** (the default never did).
- It's still **one shared folder** — safe for parallel **reads/analysis**, but **not** for parallel edits
  (same collision risk as `none`, just relocated from the global workdir into the project folder).

### `isolated` — each sub gets its own worktree + branch

| Scenario | What happens to subs |
|---|---|
| `isolated` + no project | Falls back to the global workdir |
| `isolated` + project that's not a git repo | Falls back to `inherit` (shared project folder) |
| `isolated` + project that is a git repo | Each sub gets its **own** git worktree + its **own** `swarm/<key>` branch → separate folders |

So with `isolated`:

- Each sub gets its **own working copy** (a worktree off the shared `.git`) on its **own branch** from the
  orchestrator's `HEAD` (subs start clean from `HEAD`; uncommitted changes in the parent are not carried).
- **Edits can't collide** — subs write in separate folders; the orchestrator's repo is untouched during the run.
- Each sub's work is **committed to its branch and preserved** for merging (the branch name is included in
  the sub's result).
- Worktrees are **reclaimed when subs finish** (plus a crash-safe sweep for runs that died early), and the
  plugin only ever touches worktrees **it** created (marker-scoped), so it coexists with other worktree
  tools or manual `git worktree` use.

If the `a0_worktree` plugin is installed it owns worktree lifecycle and `isolated` delegates to it;
otherwise swarm manages an inline worktree itself.

### Changing the setting

`subagent_workspace` is a single **global** setting — it applies to every `delegate_parallel` call.

- **In the UI:** Settings → **Agent** section → **A0 Swarm** → the **Subagent workspace** dropdown
  (`none` / `inherit` / `isolated`). The change takes effect on the next `delegate_parallel` call — no restart.
- **On disk:** the shipped default lives in `default_config.yaml` (`subagent_workspace: none`); your saved
  choice is stored in `config.json`. The tool reads the merged value (your `config.json` over the default)
  at call time.

### Using with a0_worktree

`isolated` works on its own (swarm manages an inline worktree). But if the
[`a0_worktree`](https://github.com/King0James0/a0-worktree-plugin) plugin is also installed, swarm
**delegates** each sub's worktree to it — `a0_worktree` is the authoritative owner of worktree
lifecycle, so the two compose cleanly instead of both managing worktrees. Detection is an exact probe
of `a0_worktree`'s versioned contract (`helpers/contract.py`); if it's absent, swarm falls back to its
inline worktree. Either way, swarm only touches worktrees it (or `a0_worktree`) created.

Cleanup in the swarm case is non-interactive (a fan-out has no human watching each sub): each sub's
worktree **checkout** is removed when that sub finishes, but its **branch is always kept** so the work
survives. Swarm surfaces each sub's branch in its result; decide what to do with the batch (merge /
keep / delete) once at the end. Installing `a0_worktree` only upgrades the `isolated` engine — it does
not change `none`/`inherit`, and `isolated` is never applied unless you select it.

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
