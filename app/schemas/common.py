"""여러 task가 같이 쓰는 형식.

필드 이름은 백엔드와 맞추면 여기만 바꾸면 된다 (키 이름은 snake_case).
"""
from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field


class Member(BaseModel):
    id: str
    name: str


class Message(BaseModel):
    id: str  # msg_N
    member_id: str
    sent_at: datetime
    text: str
    anonymous: bool = Field(False, description="Pubble에게만 말하기 (채팅에는 안 보이고 현황판, AI에만 들어감)")
    user_reply_to: str | None = Field(None, description="답장 기능으로 지정한 대상 메시지 ID (답장이 아니면 null)")


class Scope(BaseModel):
    project_id: str
    chat_room_id: str
    agenda_id: str | None = Field(None, description="진행 중인 안건이 없으면 비움")


class Evidenced(BaseModel):
    """화면에 보일 문장 하나 + 근거 ID."""

    text: str
    evidence: list[str]
    verified: bool | None = Field(None, description="검증 결과. 응답에는 통과한 문장만 담김")
    verify_score: float | None = Field(None, description="검증 점수 (0~1). 통과 기준 조정용")


class TodoItem(BaseModel):
    task: str
    owner_id: str
    due: date | None = None
    evidence: list[str]
    existing_todo_id: str | None = Field(
        None, description="이미 할당된 할 일이면 그 ID (결론에 보이기만 하고 새로 등록하지 않음)"
    )
    verified: bool | None = None
    verify_score: float | None = None


class AssignedTodo(BaseModel):
    """이미 할당된 할 일 (진행 중, 완료)."""

    id: str
    task: str
    owner_id: str
    due: date | None = None


class WriteStatus(str, Enum):
    ok = "ok"
    no_conclusion = "no_conclusion"  # 결론 없음 (합의가 없음)
    skipped = "skipped"  # 쓴 결과가 검증에서 전부 걸러짐
    failed = "failed"  # 재시도, 대체까지 실패 → 백엔드는 화면 유지 / '생성 실패'


class Source(str, Enum):
    local = "local"  # 자체 모델 (Qwen3-1.7B)
    api = "api"  # Claude Haiku 5.5
    none = "none"


class WriteMeta(BaseModel):
    status: WriteStatus
    source: Source = Source.none
    attempts: int = 0
