"""POST /board 요청과 응답 형식 (Pydantic).

API 표가 바뀌면 이 파일만 고친다. 계산 규칙은 app/services/board.py에 있다.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.services import board as domain

PointType = Literal["제안", "의견", "질문", "요청", "정보", "할 일"]
Stance = Literal["찬성", "반대", "조건부", "없음"]
ReactionKind = Literal["동의", "반대", "확인"]
Relation = Literal["같음", "반대"]


# ---------------------------------------------------------------- 요청

class PointIn(BaseModel):
    id: str
    text: str
    type: PointType
    stance: Stance
    reason: Optional[str] = None
    target: Optional[str] = None
    owner: Optional[str] = None
    due: Optional[str] = None
    evidence: list[str]
    # 구조화 출력에는 없다. 백엔드가 근거 메시지에서 붙여서 보낸다.
    speaker: str
    anonymous: bool = False


class ReactionIn(BaseModel):
    id: str  # 반응 메시지의 ID
    speaker: str
    anonymous: bool = False
    reaction: ReactionKind
    reply_to: Optional[str] = None
    reply_confidence: Optional[float] = None


class ClusterPointIn(BaseModel):
    id: str
    relation: Relation


class ClusterIn(BaseModel):
    id: str
    points: list[ClusterPointIn]


class BoardRequest(BaseModel):
    points: list[PointIn]
    clusters: list[ClusterIn] = Field(default_factory=list)
    reactions: list[ReactionIn] = Field(default_factory=list)

    def to_domain(self) -> tuple[list[domain.Point], list[domain.Cluster], list[domain.Reaction]]:
        points = [
            domain.Point(
                id=p.id,
                text=p.text,
                type=p.type,
                stance=p.stance,
                speaker=p.speaker,
                evidence=tuple(p.evidence),
                anonymous=p.anonymous,
                reason=p.reason,
                target=p.target,
                owner=p.owner,
                due=p.due,
            )
            for p in self.points
        ]
        clusters = [
            domain.Cluster(c.id, tuple(domain.ClusterPoint(cp.id, cp.relation) for cp in c.points))
            for c in self.clusters
        ]
        reactions = [
            domain.Reaction(
                id=r.id,
                speaker=r.speaker,
                reaction=r.reaction,
                reply_to=r.reply_to,
                reply_confidence=r.reply_confidence,
                anonymous=r.anonymous,
            )
            for r in self.reactions
        ]
        return points, clusters, reactions


# ---------------------------------------------------------------- 응답

class PersonOut(BaseModel):
    name: str  # 익명이면 "익명 N"
    reason: Optional[str] = None
    evidence: list[str]


class ItemOut(BaseModel):
    id: str  # 묶음 ID, solo:포인트ID, 포인트 ID처럼 입력이 같으면 항상 같은 값
    text: str
    people: list[PersonOut] = Field(default_factory=list)
    opponents: list[PersonOut] = Field(default_factory=list)  # 갈림 칸의 반대편
    target: Optional[str] = None  # 확인 필요 칸의 받는 사람 (없으면 전원)
    owner: Optional[str] = None  # 할 일 칸의 담당자
    due: Optional[str] = None
    evidence: list[str]


class BoardResponse(BaseModel):
    # 제외된 반응(excluded_reactions)은 평가용이라 응답에 넣지 않는다. 계산 결과(Board)에만 있다.
    common: list[ItemOut]
    split: list[ItemOut]
    new: list[ItemOut]
    need_check: list[ItemOut]
    todos: list[ItemOut]

    @classmethod
    def from_domain(cls, board: domain.Board) -> "BoardResponse":
        def item(i: domain.Item) -> ItemOut:
            return ItemOut(
                id=i.id,
                text=i.text,
                people=[PersonOut(name=p.name, reason=p.reason, evidence=p.evidence) for p in i.people],
                opponents=[PersonOut(name=p.name, reason=p.reason, evidence=p.evidence) for p in i.opponents],
                target=i.target,
                owner=i.owner,
                due=i.due,
                evidence=i.evidence,
            )

        return cls(
            common=[item(i) for i in board.common],
            split=[item(i) for i in board.split],
            new=[item(i) for i in board.new],
            need_check=[item(i) for i in board.need_check],
            todos=[item(i) for i in board.todos],
        )
