"""글 쓰기 3개 task(구조화, 상황 요약, 결론)의 요청/응답.

기준 문서: 노션 '구조화 출력 JSON 스키마 확정' 카드, '합성 대화 데이터 생성 기준 (v2)',
'[백엔드 전달] 바뀐 기능 + AI 서버 API 초안'
"""
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.board import BoardResponse
from app.schemas.common import AssignedTodo, Evidenced, Member, Message, Scope, TodoItem, WriteMeta

PointType = Literal["제안", "의견", "질문", "요청", "정보", "할 일"]
Stance = Literal["찬성", "반대", "조건부", "없음"]
AgendaForm = Literal["아이디어 모으기", "선택", "진행 공유", "문제 해결"]


# ---------- 구조화: 메시지 → 포인트 ----------
class OpenItem(BaseModel):
    """지금 현황판 확인 필요 칸에 있는 질문·요청."""

    id: str  # 포인트 ID (msg_N-순번)
    text: str
    speaker: str


class StructureRequest(Scope):
    agenda_title: str
    agenda_form: AgendaForm | None = None
    members: list[Member]
    message: Message = Field(description="반응 분류가 '내용 있음'으로 본 메시지")
    recent_messages: list[Message] = Field(
        default_factory=list, description="같은 안건의 앞 메시지 3~5개. 답장 대상 메시지가 없으면 추가해서 보냄"
    )
    open_items: list[OpenItem] = Field(default_factory=list)
    now: date = Field(description="기준 날짜 ('담주까지' 같은 상대 날짜 계산용)")


class Point(BaseModel):
    """필드 순서 고정 (학습 데이터 형식과 같음)."""

    id: str = Field(description="코드가 붙임: 메시지 ID + 순번 (msg_4-1)")
    text: str
    type: PointType
    stance: Stance
    reason: str | None = None
    target: str | None = Field(None, description="무엇에 대한 말인지 주제 텍스트. 질문·요청은 받는 사람 또는 '전원'")
    owner: str | None = Field(None, description="할 일의 담당자 팀원 ID")
    due: date | None = None
    answer_to: str | None = Field(None, description="이 포인트가 답한 질문·요청의 포인트 ID (open_items 중)")
    evidence: list[str]
    verify_score: float | None = None


class StructureResponse(WriteMeta):
    points: list[Point] = []


# ---------- 상황 요약: 현황판 → 2~3문장 ----------
class SummaryRequest(Scope):
    agenda_title: str
    board: BoardResponse = Field(description="/board 응답 그대로")


class SummaryResponse(WriteMeta):
    sentences: list[Evidenced] = Field([], description="2~3문장. evidence는 현황판 항목 ID")


# ---------- 결론: [종료] 뒤 결론 초안 ----------
class ConclusionDraft(BaseModel):
    decision: Evidenced | None = Field(None, description="합의가 없으면 null (결론 없음)")
    todos: list[TodoItem] = []
    open_issues: list[Evidenced] = []
    flow: list[Evidenced] = Field([], description="논의 흐름 3~5줄 (회의록용)")


class ConclusionRequest(Scope):
    agenda_title: str
    members: list[Member]
    board: BoardResponse
    evidence_messages: list[Message] = Field(description="현황판 항목의 근거 메시지 (익명 포함)")
    base_date: date
    existing_todos: list[AssignedTodo] = []


class ConclusionResponse(WriteMeta):
    draft: ConclusionDraft | None = None
