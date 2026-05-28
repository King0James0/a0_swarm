### delegate_parallel
Spawn multiple subagents to work on independent tasks in parallel. Each agent runs concurrently in its own isolated context and returns its result when done. Use this when a task decomposes into independent subtasks with no sequential dependency between them.

All tasks in one `delegate_parallel` call share a single swarm run. Agents in the same run can message each other and the orchestrator with `swarm_message`. Use meaningful `label` values — the swarm panel uses them for observability.

Args:
- `tasks` (list, required): array of task objects. Each object:
  - `label` (string, required): human-readable name shown in the swarm panel (e.g. "Researcher", "Code Writer").
  - `task` (string, required): full task description for that agent.
  - `profile` (string, optional): Agent Zero profile for a local subagent.
  - `endpoint` (string, optional): route this task to a configured remote A2A Agent Zero instance by its settings `label` or a full `http(s)://host:port` URL. Test remotes in Plugin Settings before relying on them.

Returns: a structured markdown summary of all agent results once every agent completes.

When `subagent_workspace` is `inherit` or `isolated`, each sub **already starts in the correct directory** (its activated project / worktree). Do NOT put an absolute `cd /a0/usr/projects/...` into a sub's `task` — phrase the work to run in the sub's **current** directory. A hardcoded `cd` makes the sub leave its workspace and write into the shared checkout, defeating isolation.

When `subagent_workspace=isolated`, each sub edits its own git worktree of the parent's repo and its result begins with a `[workspace: committed to branch ... in repo ...]` line. That branch lives in the **parent repo's** `.git` and holds the sub's committed work — the temporary worktree checkout is removed afterward but the **branch persists and is mergeable**. Report these branches to the user as work to merge; do NOT describe them as ephemeral or as "not landing in the repo."

Example:
~~~json
{
  "thoughts": ["I'll split this into research and implementation tasks."],
  "tool_name": "delegate_parallel",
  "tool_args": {
    "tasks": [
      {"label": "Researcher", "task": "Research the top 5 Python async frameworks and summarize their tradeoffs."},
      {"label": "Implementer", "task": "Write a working FastAPI hello-world server with JWT auth."}
    ]
  }
}
~~~
