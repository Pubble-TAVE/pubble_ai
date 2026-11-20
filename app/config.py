"""환경 변수로 어떤 LLM을 쓸지 정한다.

LLM_PRIMARY=openai  : 지금 (S4 1차 통합까지 선생 LLM API로)
LLM_PRIMARY=local   : 자체 모델 (S8 이후), 실패하면 OpenAI로 대체
"""
import os
from dataclasses import dataclass

from app.schemas.common import Source


@dataclass
class Settings:
    llm_primary: str = os.getenv("LLM_PRIMARY", "openai")  # openai | local
    llm_fallback: str = os.getenv("LLM_FALLBACK", "openai")  # openai | none
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    openai_model: str | None = os.getenv("OPENAI_MODEL")  # 정답 품질 테스트(S3) 후 결정
    local_base_url: str = os.getenv("LOCAL_BASE_URL", "http://localhost:8080/v1")
    local_model: str = os.getenv("LOCAL_MODEL", "qwen3-1.7b-pubble")
    max_retries: int = int(os.getenv("LLM_MAX_RETRIES", "1"))  # 같은 모델로 다시 쓰는 횟수
    verify_timeout: float = float(os.getenv("VERIFY_TIMEOUT", "10"))  # 검증기 시간 초과 (초) → 실패


def build_clients(s: Settings):
    """(primary, fallback) 클라이언트를 만든다. fallback은 없을 수 있다."""
    from app.llm.openai_compat import OpenAICompatClient

    def openai_client():
        if not s.openai_model:
            raise RuntimeError("OPENAI_MODEL 환경 변수를 정해주세요")
        return OpenAICompatClient(model=s.openai_model, source=Source.api, api_key=s.openai_api_key)

    def local_client():
        return OpenAICompatClient(
            model=s.local_model, source=Source.local, base_url=s.local_base_url, disable_thinking=True
        )

    primary = local_client() if s.llm_primary == "local" else openai_client()
    fallback = None
    if s.llm_primary == "local" and s.llm_fallback == "openai":
        fallback = openai_client()
    return primary, fallback
