from helpers.extension import Extension
from usr.plugins.a0_swarm.helpers.registry import SwarmRegistry


def _approx_tokens(text: str) -> int:
    try:
        from helpers import tokens
        return int(tokens.approximate_tokens(text or ""))
    except Exception:
        return max(1, len(text or "") // 4) if text else 0


class SwarmTokenUsage(Extension):
    async def execute(self, call_data: dict | None = None, response: str = "", reasoning: str = "", **kwargs):
        if not self.agent:
            return

        reg = SwarmRegistry.get()
        entry = reg.get_agent_by_context(self.agent.context.id)
        if not entry:
            return

        ctx_window = self.agent.get_data("ctx_window") or {}
        input_tokens = int(ctx_window.get("tokens") or 0)
        output_tokens = _approx_tokens((response or "") + "\n" + (reasoning or ""))
        reg.add_token_usage(entry.agent_name, input_tokens=input_tokens, output_tokens=output_tokens)
