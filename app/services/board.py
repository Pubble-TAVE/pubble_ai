"""현황판 5칸 계산 (규칙). 모델 호출 없음.

포인트, 묶음, 반응, 팀원을 받아서 공통, 갈림, 새로움, 확인 필요, 할 일 5칸으로 나눈다.
AI 서버는 상태를 저장하지 않으므로 매번 받은 입력 전체로 새로 계산한다.
그래서 반응이 생기면 새로움이 공통이나 갈림으로 "이동"하는 것도 재계산으로 처리된다.

이 파일은 스키마(Pydantic)를 모른다. 요청과 응답 형식이 바뀌면 app/schemas/board.py만 고친다.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional, Sequence

from app.config import BoardSettings, board_settings

# 공통, 갈림, 새로움 칸에 들어가는 포인트 유형 (주장 포인트)
CLAIM_TYPES = {"제안", "의견", "정보"}
# 답이 필요한 유형 (확인 필요 칸 후보)
ASK_TYPES = {"질문", "요청"}
# 다른 포인트에 대한 응답으로 보는 입장
RESPONSE_STANCES = {"찬성", "조건부", "반대"}


# ---------------------------------------------------------------- 입력

@dataclass(frozen=True)
class Point:
    """구조화가 만든 포인트. 포인트 ID는 msg_N-순번 형식이다."""

    id: str
    text: str
    type: str
    stance: str
    speaker: str
    evidence: tuple[str, ...]
    anonymous: bool = False
    reason: Optional[str] = None
    target: Optional[str] = None
    owner: Optional[str] = None
    due: Optional[str] = None


@dataclass(frozen=True)
class Reaction:
    """반응 분류 결과 (동의, 반대, 확인). id는 반응 메시지의 ID."""

    id: str
    speaker: str
    reaction: str
    reply_to: Optional[str] = None
    reply_confidence: Optional[float] = None
    anonymous: bool = False


@dataclass(frozen=True)
class ClusterPoint:
    id: str
    relation: str  # 같음 또는 반대


@dataclass(frozen=True)
class Cluster:
    id: str
    points: tuple[ClusterPoint, ...]


# ---------------------------------------------------------------- 출력

@dataclass
class Person:
    name: str
    reason: Optional[str] = None
    evidence: list[str] = field(default_factory=list)


@dataclass
class Item:
    id: str
    text: str
    people: list[Person] = field(default_factory=list)
    opponents: list[Person] = field(default_factory=list)
    target: Optional[str] = None
    owner: Optional[str] = None
    due: Optional[str] = None
    evidence: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ExcludedReaction:
    """인원수에 넣지 않은 반응. 제외된 반응 비율을 평가에 쓰려고 남긴다."""

    id: str
    why: str


@dataclass
class Board:
    common: list[Item] = field(default_factory=list)
    split: list[Item] = field(default_factory=list)
    new: list[Item] = field(default_factory=list)
    need_check: list[Item] = field(default_factory=list)
    todos: list[Item] = field(default_factory=list)
    excluded_reactions: list[ExcludedReaction] = field(default_factory=list)


# ---------------------------------------------------------------- 내부 도구

@dataclass
class _Contribution:
    """한 사람이 한 묶음에 낸 의견 (포인트 또는 반응)."""

    speaker: str
    anonymous: bool
    reason: Optional[str]
    evidence: list[str]
    order: int  # 메시지 순서. 입장을 바꾼 사람은 나중 의견을 따른다.


@dataclass
class _Group:
    id: str
    rep: Optional[Point] = None
    supporters: dict[str, _Contribution] = field(default_factory=dict)
    opponents: dict[str, _Contribution] = field(default_factory=dict)


def message_id_of(point: Point) -> str:
    """포인트가 나온 메시지 ID. msg_4-1 -> msg_4"""
    head, sep, _ = point.id.rpartition("-")
    if sep and head:
        return head
    return point.evidence[0] if point.evidence else point.id


def _order_of(message_ids: Sequence[str]) -> int:
    """msg_12 -> 12. 숫자가 없으면 0."""
    numbers = [int(n) for mid in message_ids for n in re.findall(r"\d+", mid)]
    return max(numbers) if numbers else 0


def _anonymous_labels(points: Sequence[Point], reactions: Sequence[Reaction]) -> dict[str, str]:
    """익명 발화자에게 처음 나온 순서대로 "익명 1", "익명 2"를 붙인다."""
    labels: dict[str, str] = {}
    for item in [*points, *reactions]:
        if item.anonymous and item.speaker not in labels:
            labels[item.speaker] = f"익명 {len(labels) + 1}"
    return labels


def _add(side: dict[str, _Contribution], other: dict[str, _Contribution], c: _Contribution) -> None:
    """한 사람은 한 묶음에서 한쪽에만 센다. 양쪽에 있으면 나중 메시지를 따른다."""
    if c.speaker in other:
        if c.order < other[c.speaker].order:
            return
        del other[c.speaker]
    old = side.get(c.speaker)
    if old is None:
        side[c.speaker] = c
        return
    for e in c.evidence:
        if e not in old.evidence:
            old.evidence.append(e)
    if old.reason is None:
        old.reason = c.reason
    old.anonymous = old.anonymous and c.anonymous
    old.order = max(old.order, c.order)


def _stance_sign(stance: str) -> int:
    return -1 if stance == "반대" else 1


def _attach_reactions(
    reactions: Sequence[Reaction],
    by_message: dict[str, list[Point]],
    settings: BoardSettings,
) -> tuple[dict[str, list[Reaction]], list[ExcludedReaction]]:
    """동의, 반대 반응을 대상 포인트에 붙인다. 못 붙인 반응은 제외 목록에 남긴다.

    대상 메시지에 포인트가 1개일 때만 그 포인트에 붙인다. 여러 개면 어느 포인트인지 모르므로
    인원수에서 뺀다. 확인 반응은 5칸 판정에 쓰지 않는다 (MVP).
    """
    attached: dict[str, list[Reaction]] = defaultdict(list)
    excluded: list[ExcludedReaction] = []
    for r in reactions:
        if r.reaction not in ("동의", "반대"):
            continue
        if r.reply_to is None:
            excluded.append(ExcludedReaction(r.id, "대상 없음"))
        elif r.reply_confidence is None or r.reply_confidence < settings.reaction_confidence_min:
            excluded.append(ExcludedReaction(r.id, "확신도 낮음"))
        else:
            targets = by_message.get(r.reply_to, [])
            if not targets:
                excluded.append(ExcludedReaction(r.id, "대상 메시지에 포인트 없음"))
            elif len(targets) > 1:
                excluded.append(ExcludedReaction(r.id, "대상 메시지에 포인트 여러 개"))
            else:
                attached[targets[0].id].append(r)
    return attached, excluded


# ---------------------------------------------------------------- 계산

def compute_board(
    points: Sequence[Point],
    clusters: Sequence[Cluster],
    reactions: Sequence[Reaction],
    settings: BoardSettings = board_settings,
) -> Board:
    """현황판 5칸을 계산한다.

    공통: 묶음 안 사람이 2명 이상이고 반대가 없음
    갈림: 반대가 1명이라도 있음 (입장 반대, 반응 반대, 관계 반대 모두. 같은 사람은 1명)
    새로움: 1명만 말했고 반응이 없음
    확인 필요: 답이 없는 질문과 요청
    할 일: 할 일 포인트와, 수락된 요청
    """
    labels = _anonymous_labels(points, reactions)
    points = [p for p in points if settings.count_anonymous or not p.anonymous]
    reactions = [r for r in reactions if settings.count_anonymous or not r.anonymous]

    by_id = {p.id: p for p in points}
    by_message: dict[str, list[Point]] = defaultdict(list)
    for p in points:
        by_message[message_id_of(p)].append(p)

    attached, excluded = _attach_reactions(reactions, by_message, settings)

    def name_of(speaker: str, anonymous: bool) -> str:
        return labels.get(speaker, speaker) if anonymous else speaker

    # 질문이나 요청에 달린 답. 답 포인트는 주장 묶음에 넣지 않는다.
    answers: dict[str, list[Point]] = defaultdict(list)
    for p in points:
        asked = by_id.get(p.target) if p.target else None
        if asked is not None and asked.type in ASK_TYPES and p.speaker != asked.speaker:
            answers[asked.id].append(p)
    answer_ids = {a.id for lst in answers.values() for a in lst}

    def is_response(p: Point) -> bool:
        """다른 포인트에 찬성, 반대, 조건부로 답한 포인트."""
        return p.target in by_id and p.stance in RESPONSE_STANCES and p.id not in answer_ids

    groups: dict[str, _Group] = {}
    # 포인트가 속한 묶음과 방향 (+1: 묶음 주장에 같은 편, -1: 반대편)
    point_group: dict[str, tuple[str, int]] = {}

    def contribution_of(p: Point) -> _Contribution:
        return _Contribution(p.speaker, p.anonymous, p.reason, list(p.evidence), _order_of(p.evidence))

    def put(group: _Group, sign: int, c: _Contribution) -> None:
        if sign > 0:
            _add(group.supporters, group.opponents, c)
        else:
            _add(group.opponents, group.supporters, c)

    # 1. 관계 판단이 만든 묶음
    for cluster in clusters:
        for cp in cluster.points:
            p = by_id.get(cp.id)
            if p is None or p.type not in CLAIM_TYPES or p.id in answer_ids or is_response(p):
                continue
            if p.id in point_group:
                continue
            sign = -1 if cp.relation == "반대" else 1
            group = groups.setdefault(cluster.id, _Group(cluster.id))
            point_group[p.id] = (group.id, sign)
            if sign > 0 and group.rep is None:
                group.rep = p
            put(group, sign, contribution_of(p))

    # 2. 묶음에 안 들어간 주장 포인트는 혼자 한 묶음
    for p in points:
        if p.type not in CLAIM_TYPES or p.id in point_group or p.id in answer_ids or is_response(p):
            continue
        group = groups.setdefault(f"solo:{p.id}", _Group(f"solo:{p.id}"))
        point_group[p.id] = (group.id, 1)
        group.rep = p
        put(group, 1, contribution_of(p))

    # 3. 다른 포인트에 답한 포인트는 대상 묶음에 붙인다. 대상이 아직 안 정해졌으면 뒤로 미룬다.
    pending = [p for p in points if is_response(p) and p.type in CLAIM_TYPES]
    while pending:
        remaining = []
        for p in pending:
            if p.target in point_group:
                gid, target_sign = point_group[p.target]
                sign = _stance_sign(p.stance) * target_sign
                point_group[p.id] = (gid, sign)
                put(groups[gid], sign, contribution_of(p))
            else:
                remaining.append(p)
        if len(remaining) == len(pending):
            # 대상이 질문이나 할 일처럼 묶음이 없는 포인트면 혼자 한 묶음으로 둔다.
            for p in remaining:
                group = groups.setdefault(f"solo:{p.id}", _Group(f"solo:{p.id}"))
                point_group[p.id] = (group.id, 1)
                group.rep = p
                put(group, 1, contribution_of(p))
            break
        pending = remaining

    # 4. 포인트에 붙은 반응. 반대편 포인트에 한 동의는 반대편이 된다.
    for point_id, rs in attached.items():
        if point_id not in point_group:
            continue
        gid, sign = point_group[point_id]
        for r in rs:
            reaction_sign = (1 if r.reaction == "동의" else -1) * sign
            put(
                groups[gid],
                reaction_sign,
                _Contribution(r.speaker, r.anonymous, None, [r.id], _order_of([r.id])),
            )

    board = Board(excluded_reactions=excluded)

    def person(c: _Contribution) -> Person:
        return Person(name_of(c.speaker, c.anonymous), c.reason, list(c.evidence))

    def evidence_of(*sides: dict[str, _Contribution]) -> list[str]:
        seen: list[str] = []
        for side in sides:
            for c in side.values():
                for e in c.evidence:
                    if e not in seen:
                        seen.append(e)
        return seen

    # 5. 묶음을 칸에 배치
    for group in groups.values():
        sup, opp = group.supporters, group.opponents
        if not sup and not opp:
            continue
        rep_text = group.rep.text if group.rep else ""
        item = Item(
            id=group.id,
            text=rep_text,
            people=[person(c) for c in sup.values()],
            opponents=[person(c) for c in opp.values()],
            evidence=evidence_of(sup, opp),
        )
        if opp:
            board.split.append(item)
        elif len(sup) >= 2:
            board.common.append(item)
        else:
            board.new.append(item)

    # 6. 확인 필요와 할 일
    for p in points:
        if p.type == "할 일":
            board.todos.append(
                Item(
                    id=p.id,
                    text=p.text,
                    people=[Person(name_of(p.speaker, p.anonymous), p.reason, list(p.evidence))],
                    owner=p.owner or name_of(p.speaker, p.anonymous),
                    due=p.due,
                    evidence=list(p.evidence),
                )
            )
        elif p.type in ASK_TYPES:
            accepted = _accepted_by(p, attached.get(p.id, []))
            if accepted:
                # 받는 사람이 동의하면 요청이 할 일이 된다.
                for r in accepted:
                    owner = name_of(r.speaker, r.anonymous)
                    board.todos.append(
                        Item(
                            id=f"todo:{p.id}:{r.speaker}",
                            text=p.text,
                            people=[Person(name_of(p.speaker, p.anonymous), p.reason, list(p.evidence))],
                            owner=owner,
                            due=p.due,
                            evidence=[*p.evidence, r.id],
                        )
                    )
            elif not answers.get(p.id):
                board.need_check.append(
                    Item(
                        id=p.id,
                        text=p.text,
                        people=[Person(name_of(p.speaker, p.anonymous), p.reason, list(p.evidence))],
                        target=p.target if p.target not in by_id else None,
                        evidence=list(p.evidence),
                    )
                )

    return board


def _accepted_by(request: Point, reactions: Sequence[Reaction]) -> list[Reaction]:
    """요청을 수락한 반응. 요청 포인트만 해당하고, 받는 사람이 정해져 있으면 그 사람의 동의만 센다."""
    if request.type != "요청":
        return []
    accepted: list[Reaction] = []
    for r in reactions:
        if r.reaction != "동의" or r.speaker == request.speaker:
            continue
        if request.target is not None and r.speaker != request.target:
            continue
        if all(a.speaker != r.speaker for a in accepted):
            accepted.append(r)
    return accepted
