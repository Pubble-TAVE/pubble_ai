"""여러 task가 같이 쓰는 형식.

필드 이름은 임시. 백엔드가 정하면 여기만 바꾸면 된다.
"""
from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field


class Member(BaseModel):
    id: str
    name: str


class Option(BaseModel):
    id: str
    name: str


class Message(BaseModel):
    id: str
    member_id: str
    sent_at: datetime
    text: str
    anonymous: bool = Field(False, description="익명 체크 메시지 (채팅에는 안 보이고 현황판, AI 모델에만 들어감)")


class OptionCount(BaseModel):
    option_id: str
    count: int


class Scope(BaseModel):
    project_id: str
    chat_room_id: str
    agenda_id: str | None = Field(None, description="진행 중인 안건이 없으면 비움")


class Evidenced(BaseModel):
    """화면에 보일 문장 하나 + 근거 메시지 ID."""

    text: str
    evidence: list[str]
    verified: bool | None = Field(None, description="검증기 결과. 응답에는 통과한 문장만 담김")


class TodoItem(BaseModel):
    task: str
    owner_id: str
    due: date | None = None
    evidence: list[str]
    existing_todo_id: str | None = Field(
        None, description="이미 할당된 할 일이면 그 ID (결론에 보이기만 하고 새로 등록하지 않음)"
    )
    verified: bool | None = None


class AssignedTodo(BaseModel):
    """이미 할당된 할 일 (진행 중, 완료)."""

    id: str
    task: str
    owner_id: str
    due: date | None = None


class WriteStatus(str, Enum):
    ok = "ok"
    no_conclusion = "no_conclusion"  # 결론 없음 (합의가 없음)
    skipped = "skipped"  # 할 일 캐치에서 담당자가 없어 할 일로 안 잡음
    failed = "failed"  # 재시도, 대체까지 실패 → 백엔드는 화면 유지 / '생성 실패'


class Source(str, Enum):
    local = "local"  # 자체 모델 (Qwen3-1.7B)
    api = "api"  # 큰 LLM API (OpenAI)
    none = "none"


class WriteMeta(BaseModel):
    status: WriteStatus
    source: Source = Source.none
    attempts: int = 0
