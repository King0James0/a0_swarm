import time

from helpers.extension import Extension
from usr.plugins.a0_swarm.helpers.registry import SwarmRegistry


_LAST_PUSH_KEY = "_a0_swarm_last_reasoning_push"
_MIN_PUSH_INTERVAL_S = 0.5
_TAIL_CHARS = 700


class SwarmLiveReasoning(Extension):
    async def execute(self, loop_data=None, stream_data: dict | None = None, **kwargs):
        if not self.agent or not isinstance(stream_data, dict):
            return

        full = str(stream_data.get("full") or "")
        chunk = str(stream_data.get("chunk") or "")
        if not full and not chunk:
            return

        now = time.monotonic()
        last = self.agent.get_data(_LAST_PUSH_KEY) or {}
        last_time = float(last.get("time") or 0)
        last_len = int(last.get("length") or 0)
        if now - last_time < _MIN_PUSH_INTERVAL_S and len(full) - last_len < 120:
            return

        reg = SwarmRegistry.get()
        entry = reg.get_agent_by_context(self.agent.context.id)
        if not entry:
            return

        self.agent.set_data(_LAST_PUSH_KEY, {"time": now, "length": len(full)})
        reg.update_live_state(
            entry.agent_name,
            activity="Reasoning...",
            live_reasoning=full[-_TAIL_CHARS:],
        )
