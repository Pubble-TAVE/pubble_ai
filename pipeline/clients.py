"""데이터 파이프라인용 LLM 호출 + 토큰 사용량 기록.

서버(app/llm/)와 달리 사용량을 같이 돌려준다 (비용 계산용).
- 대화 생성: Gemini Flash-Lite (OpenAI 호환 base_url, 연 크레딧)
- 정답 라벨: Claude Haiku 5.5 (system 캐싱)
"""
import re
from dataclasses import dataclass, field

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


@dataclass
class Usage:
    model: str
    step: str  # generate / structure / cluster / summary
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class UsageLog:
    rows: list[Usage] = field(default_factory=list)

    def add(self, u: Usage) -> None:
        self.rows.append(u)


class ClaudeCaller:
    def __init__(self, model: str, effort: str, api_key: str | None = None, max_tokens: int = 8000):
        from anthropic import AsyncAnthropic

        self.model, self.effort, self.max_tokens = model, effort, max_tokens
        self._client = AsyncAnthropic(api_key=api_key, timeout=120.0)

    async def call(self, step: str, system: str, user: str, log: UsageLog) -> str:
        resp = await self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            output_config={"effort": self.effort},
        )
        u = resp.usage
        log.add(Usage(
            model=self.model, step=step, input_tokens=u.input_tokens, output_tokens=u.output_tokens,
            cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
        ))
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        return _FENCE.sub("", text.strip()).strip()


class GeminiCaller:
    """Gemini를 OpenAI 호환 API로 부른다."""

    def __init__(self, model: str, api_key: str | None, base_url: str):
        from openai import AsyncOpenAI

        self.model = model
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=300.0)

    async def call(self, step: str, system: str, user: str, log: UsageLog) -> str:
        resp = await self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            temperature=0.9,  # 대화는 다양하게
        )
        u = resp.usage
        log.add(Usage(model=self.model, step=step, input_tokens=u.prompt_tokens if u else 0,
                      output_tokens=u.completion_tokens if u else 0))
        return _FENCE.sub("", (resp.choices[0].message.content or "").strip()).strip()
