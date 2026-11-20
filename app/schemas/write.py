"""글 쓰기 5개 task의 요청/응답."""
from datetime import date

from pydantic import BaseModel, Field

from app.schemas.common import (
    AssignedTodo,
    Evidenced,
    Member,
    Message,
    Option,
    OptionCount,
    Scope,
    TodoItem,
    WriteMeta,
)


# ---------- board_summary: 현황판 쟁점, 합의 ----------
class BoardSummaryRequest(Scope):
    agenda_title: str
    options: list[Option]
    members: list[Member]
    counts: list[OptionCount]
    messages: list[Message] = Field(description="그 안건의 최근 메시지. 익명 메시지는 서버에서 뺌")


class BoardSummaryResponse(WriteMeta):
    issues: list[Evidenced] = []
    agreements: list[Evidenced] = []


# ---------- conclusion: 결론 초안 + 할 일 + 미결 사항 + 논의 흐름 ----------
class ConclusionDraft(BaseModel):
    decision: Evidenced | None = Field(None, description="합의가 없으면 null (결론 없음)")
    todos: list[TodoItem] = []
    open_issues: list[Evidenced] = []
    flow: list[Evidenced] = Field([], description="논의 흐름 3~5줄 (회의록용)")


class ConclusionRequest(Scope):
    agenda_title: str
    options: list[Option]
    members: list[Member]
    counts: list[OptionCount]
    vote_result: list[OptionCount] | None = None
    messages: list[Message] = Field(description="그 안건의 전체 메시지 (익명 메시지 포함)")
    base_date: date
    assigned_todos: list[AssignedTodo] = []
    previous_draft: ConclusionDraft | None = Field(None, description="[수정 요청]으로 다시 쓸 때만")
    revision_request: str | None = Field(None, description="[수정 요청] 한 줄")


class ConclusionResponse(WriteMeta):
    draft: ConclusionDraft | None = None


# ---------- option_normalize: 선택지 정리 ----------
class OptionNormalizeRequest(Scope):
    agenda_title: str
    message: Message
    options: list[Option]


class OptionNormalizeResponse(WriteMeta):
    name: str | None = None
    matched_option_id: str | None = Field(None, description="기존 선택지와 같으면 그 ID, 새 선택지면 null")
    evidence: list[str] = []


# ---------- todo_catch: 할 일 캐치 ----------
class TodoCatchRequest(Scope):
    message: Message
    previous_message: Message | None = None
    members: list[Member]


class TodoCatchResponse(WriteMeta):
    todo: TodoItem | None = None
    display_text: str | None = Field(None, description="담당자에게 보낼 요청 문구 (템플릿)")


# ---------- next_agenda: 추천 다음 안건 ----------
class AgendaCandidate(BaseModel):
    title: str
    reason: str
    evidence: list[str]
    chat_room_id: str


class NextAgendaRequest(Scope):
    open_issues: list[Evidenced] = Field([], description="끝난 안건의 미결 사항 (근거 포함)")
    other_agenda_messages: list[Message] = Field([], description="'다른 안건'으로 분류된 메시지")
    existing_candidates: list[str] = []
    existing_agendas: list[str] = Field([], description="같은 프로젝트의 기존 안건 제목")


class NextAgendaResponse(WriteMeta):
    candidates: list[AgendaCandidate] = []
