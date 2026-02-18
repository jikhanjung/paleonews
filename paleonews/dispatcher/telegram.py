import logging

from telegram import Bot

from .base import BaseDispatcher

logger = logging.getLogger(__name__)


class TelegramDispatcher(BaseDispatcher):
    def __init__(self, bot_token: str, chat_id: str, max_length: int = 4096):
        self.bot = Bot(token=bot_token)
        self.chat_id = chat_id
        self.max_length = max_length

    def split_message(self, text: str) -> list[str]:
        """Split long message into chunks at article boundaries."""
        if len(text) <= self.max_length:
            return [text]

        chunks = []
        # Split on article separator
        separator = "\n" + "─" * 22 + "\n"
        sections = text.split(separator)

        current = ""
        for section in sections:
            candidate = current + separator + section if current else section
            if len(candidate) > self.max_length and current:
                chunks.append(current.strip())
                current = section
            else:
                current = candidate

        if current.strip():
            chunks.append(current.strip())

        return chunks if chunks else [text[:self.max_length]]

    async def send_briefing(self, briefing: str) -> bool:
        """Send briefing to Telegram chat. Returns True on success."""
        chunks = self.split_message(briefing)
        try:
            for chunk in chunks:
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=chunk,
                )
            logger.info("Sent %d message(s) to Telegram chat %s", len(chunks), self.chat_id)
            return True
        except Exception:
            logger.exception("Failed to send Telegram message")
            return False
