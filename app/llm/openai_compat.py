"""OpenAI 호환 API를 쓰는 모델을 같은 코드로 부른다.

- 자체 모델: Qwen3-1.7B GGUF를 llama-server로 띄우고 LOCAL_BASE_URL로 연결
- 대화 생성(Gemini Flash-Lite)도 OpenAI 호환 base_url로 부를 수 있다 (데이터 파이프라인)
선생 LLM과 결론은 Claude라서 anthropic_client.py를 쓴다.
"""
import re

from openai import AsyncOpenAI

from app.schemas.common import Source

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


class OpenAICompatClient:
    def __init__(
        self,
        model: str,
        source: Source,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 60.0,
        disable_thinking: bool = False,
    ):
        self.model = model
        self.source = source
        self.disable_thinking = disable_thinking
        self._client = AsyncOpenAI(api_key=api_key or "not-needed", base_url=base_url, timeout=timeout)

    async def complete(self, system: str, user: str) -> str:
        extra = {}
        if self.disable_thinking:
            # Qwen3 non-thinking 모드
            extra["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
        resp = await self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            temperature=0.2,
            **extra,
        )
        text = resp.choices[0].message.content or ""
        return _THINK.sub("", text).strip()
