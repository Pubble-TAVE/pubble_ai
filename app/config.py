"""환경 변수로 어떤 LLM을 쓸지 정한다.

LLM_PRIMARY=api    : 지금 (자체 모델 학습 전까지 Claude Haiku 5.5로)
LLM_PRIMARY=local  : 자체 모델 (Qwen3-1.7B, llama-server), 실패하면 Claude로 대체
결론은 항상 Claude (자체 모델로 바꾸지 않음).
"""
import os
from dataclasses import dataclass

from app.schemas.common import Source


@dataclass
class Settings:
    llm_primary: str = os.getenv("LLM_PRIMARY", "api")  # api | local
    llm_fallback: str = os.getenv("LLM_FALLBACK", "api")  # api | none (local일 때 대체)
    anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY")
    claude_model: str = os.getenv("CLAUDE_MODEL", "claude-haiku-5-5")
    claude_effort: str = os.getenv("CLAUDE_EFFORT", "medium")  # low/medium 비교 후 medium으로 결정
    local_base_url: str = os.getenv("LOCAL_BASE_URL", "http://localhost:8080/v1")
    local_model: str = os.getenv("LOCAL_MODEL", "qwen3-1.7b-pubble")
    max_retries: int = int(os.getenv("LLM_MAX_RETRIES", "1"))  # 같은 모델로 다시 쓰는 횟수
    verify_timeout: float = float(os.getenv("VERIFY_TIMEOUT", "10"))  # 검증기 시간 초과 (초) → 실패


def build_clients(s: Settings):
    """(primary, fallback, conclusion) 클라이언트. fallback은 없을 수 있다."""
    from app.llm.anthropic_client import AnthropicClient
    from app.llm.openai_compat import OpenAICompatClient

    def claude():
        return AnthropicClient(model=s.claude_model, effort=s.claude_effort, api_key=s.anthropic_api_key)

    def local():
        return OpenAICompatClient(
            model=s.local_model, source=Source.local, base_url=s.local_base_url, disable_thinking=True
        )

    primary = local() if s.llm_primary == "local" else claude()
    fallback = claude() if s.llm_primary == "local" and s.llm_fallback == "api" else None
    return primary, fallback, claude()


@dataclass(frozen=True)
class BoardSettings:
    """현황판 5칸 계산 설정."""

    # 반응의 대상 확신도가 이 값보다 낮으면 인원수에서 제외한다.
    # 임시값이다. 반응 분류 모델 평가 후 조정한다.
    reaction_confidence_min: float = 0.5

    # 익명 의견을 현황판에 넣을지. 가은 안: 넣고 "익명 N"으로 표시한다.
    # False면 익명 포인트와 익명 반응을 계산에서 아예 뺀다.
    count_anonymous: bool = True


board_settings = BoardSettings()
