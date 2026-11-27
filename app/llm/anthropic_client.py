"""Claude API (선생 LLM, 결론, 자체 모델이 실패했을 때 대체).

- 모델: Claude Haiku 5.5. 다른 모델 비교 없이 effort만 조절한다 (CLAUDE_EFFORT).
- system(작성 기준 + 예시)은 길고 매번 같아서 프롬프트 캐싱을 건다.
- 출력은 JSON 하나. 코드 블록(```json)으로 감싸 오면 벗겨낸다.
"""
import re

from anthropic import AsyncAnthropic

from app.schemas.common import Source

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


class AnthropicClient:
    source = Source.api

    def __init__(
        self,
        model: str,
        effort: str = "medium",
        api_key: str | None = None,
        max_tokens: int = 8000,
        timeout: float = 60.0,
    ):
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens  # 생각(thinking) 토큰도 여기 포함되므로 넉넉하게
        self._client = AsyncAnthropic(api_key=api_key, timeout=timeout)

    async def complete(self, system: str, user: str) -> str:
        resp = await self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            output_config={"effort": self.effort},
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        return _FENCE.sub("", text.strip()).strip()
