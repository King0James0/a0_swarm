from helpers.extension import Extension
from usr.plugins.a0_swarm.helpers import delivery


class SwarmCaptureReply(Extension):
    async def execute(
        self,
        tool_name: str = "",
        response=None,
        **kwargs,
    ):
        if tool_name != "response" or response is None or not self.agent:
            return

        delivery.capture_pending_reply(self.agent, getattr(response, "message", ""))
