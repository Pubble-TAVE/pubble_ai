"""근거 검증기 연결 지점 (검증기 모델은 연 담당).

AI 서버 안에서 글 쓰기 결과의 문장마다 (문장, 근거 메시지 원문)을 넘겨
근거가 맞는지 확인한다. 지금은 통과만 시키는 자리표시자.
연의 NLI 검증기가 준비되면 같은 인터페이스로 바꿔 끼우면 된다.
"""
from typing import Protocol


class Verifier(Protocol):
    async def verify(self, sentence: str, evidence_texts: list[str]) -> bool: ...


class PassThroughVerifier:
    async def verify(self, sentence: str, evidence_texts: list[str]) -> bool:
        return True
