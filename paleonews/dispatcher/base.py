from abc import ABC, abstractmethod


class BaseDispatcher(ABC):
    @abstractmethod
    async def send_briefing(self, briefing: str) -> bool:
        """Send briefing text. Returns True on success."""
        ...
