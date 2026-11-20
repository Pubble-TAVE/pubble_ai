"""근거 검증기 연결 지점 (검증기 모델은 연 담당).

AI 서버 안에서 글 쓰기 결과의 문장마다 (task, 문장, 근거 메시지)를 넘겨
근거가 맞는지 확인한다. 지금은 근거가 있으면 통과시키는 자리표시자.
연의 NLI 검증기가 준비되면 같은 인터페이스로 바꿔 끼우면 된다.

- task: 글마다 추가로 확인할 규칙이 달라서 받음 (예: todo_catch는 담당자와 마감 확인)
- evidence: 메시지 ID, 보낸 사람 이름, 내용 (문장에 이름이 자주 나와서 말한 사람이 필요)
- 결과: passed, score(0~1), reason (통과 기준 조정과 막힌 이유 확인용)
- 근거가 비었거나 검증기 오류(예외, 시간 초과)는 writer.py에서 실패로 처리
"""
from typing import Protocol

from pydantic import BaseModel


class Evidence(BaseModel):
    message_id: str
    speaker: str  # 익명 메시지는 "익명"
    text: str


class VerifyResult(BaseModel):
    passed: bool
    score: float
    reason: str | None = None


class Verifier(Protocol):
    async def verify(self, task: str, sentence: str, evidence: list[Evidence]) -> VerifyResult: ...


class PassThroughVerifier:
    async def verify(self, task: str, sentence: str, evidence: list[Evidence]) -> VerifyResult:
        if not evidence:
            return VerifyResult(passed=False, score=0.0, reason="근거 없음")
        return VerifyResult(passed=True, score=1.0)
