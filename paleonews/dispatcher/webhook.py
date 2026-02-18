import logging

import httpx

from .base import BaseDispatcher

logger = logging.getLogger(__name__)


class WebhookDispatcher(BaseDispatcher):
    def __init__(self, webhook_url: str, platform: str = "slack"):
        self.webhook_url = webhook_url
        self.platform = platform

    def _format_payload(self, briefing: str) -> dict:
        """Format payload for the target platform."""
        if self.platform == "discord":
            return {"content": briefing[:2000]}
        # Slack (default)
        return {"text": briefing}

    async def send_briefing(self, briefing: str) -> bool:
        """Send briefing via webhook."""
        payload = self._format_payload(briefing)
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(self.webhook_url, json=payload)
                response.raise_for_status()
            logger.info("Webhook sent to %s", self.platform)
            return True
        except Exception:
            logger.exception("Failed to send %s webhook", self.platform)
            return False
