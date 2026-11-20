from typing import Protocol

from app.schemas.common import Source


class LLMClient(Protocol):
    source: Source

    async def complete(self, system: str, user: str) -> str:
        """JSON 문자열 하나를 돌려준다."""
        ...
