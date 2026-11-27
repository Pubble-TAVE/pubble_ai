"""대화 → 선생 라벨 (Claude): 구조화, 묶음, 시점별 상황 요약.

- 구조화 입력은 서버와 같은 프롬프트(app/services/prompts.py) → (user 프롬프트, 선생 답) = 학습 쌍
- open_items(답이 아직 없는 질문·요청)는 앞 메시지의 라벨에서 계산해서 넘긴다
- 상황 요약은 25, 50, 75, 100% 시점에 현황판을 코드(app/services/board.py)로 계산하고 그걸 입력으로
"""
import json
from datetime import datetime

from app.schemas.board import BoardResponse
from app.schemas.common import Member, Message
from app.schemas.write import OpenItem
from app.services import board as board_rules
from app.services import prompts
from app.services.dates import resolve_due
from app.services.teacher_guides import teacher_system
from pipeline.clients import UsageLog

TYPES = {"제안", "의견", "질문", "요청", "정보", "할 일"}
STANCES = {"찬성", "반대", "조건부", "없음"}
CHECKPOINTS = (0.25, 0.5, 0.75, 1.0)

CLUSTER_SYSTEM = prompts.SYSTEM + """

[cluster 작성 기준]
- 같은 말(다른 표현 포함)을 한 포인트끼리 묶는다. 묶음마다 기준이 되는 안이 있고, 각 포인트는 그 안에 같음 / 반대.
  예: "놓친 내용 요약 빼기"(찬성)와 "놓친 내용 요약 빼기"(반대)는 같은 묶음, 관계는 같음 / 반대.
- 조건부는 같음으로 묶는다 (반대가 아님).
- 혼자인 포인트도 자기 묶음 하나로 둔다.
- 안건과 관계없는 포인트는 off_topic.
- 질문, 요청, 할 일은 묶지 않는다 (입력에 없음).
출력 형식: {"clusters": [{"id": "c1", "points": [{"id": "msg_3-2", "relation": "같음"}]}], "off_topic": ["msg_9-1"]}"""


def to_messages(dialog: dict) -> list[Message]:
    return [
        Message(id=m["id"], member_id=m["speaker"], sent_at=datetime.fromisoformat(m["time"]), text=m["text"],
                anonymous=bool(m.get("anonymous")), user_reply_to=m.get("user_reply_to"))
        for m in dialog["messages"]
    ]


def check_points(points, valid_ids: set[str], open_ids: set[str]) -> list[str]:
    """선생 라벨 형식 검사 (스키마 카드 '거르기 기준')."""
    if not isinstance(points, list):
        return ["points가 목록이 아님"]
    problems = []
    for p in points:
        if p.get("type") not in TYPES or p.get("stance") not in STANCES:
            problems.append(f"정해진 값 밖: {p.get('type')}, {p.get('stance')}")
        if not p.get("evidence") or any(e not in valid_ids for e in p["evidence"]):
            problems.append(f"근거 ID 문제: {p.get('evidence')}")
        if p.get("type") == "할 일" and not p.get("owner"):
            problems.append("할 일인데 owner 없음")
        if p.get("answer_to") is not None and p["answer_to"] not in open_ids:
            problems.append(f"answer_to가 목록에 없음: {p['answer_to']}")
    return problems


async def label_dialog(order: dict, dialog: dict, claude, log: UsageLog, recent_n: int = 5) -> dict:
    members = [Member(id=m["id"], name=m["name"]) for m in order["members"]]
    names = {m.id: m.name for m in members}
    msgs = to_messages(dialog)
    by_id = {m.id: m for m in msgs}
    reaction_of = {m["id"]: m for m in dialog["messages"]}

    structure: dict[str, dict] = {}
    all_points: list[dict] = []  # 코드가 ID를 붙인 포인트 (speaker 포함)
    open_items: dict[str, OpenItem] = {}

    # 1. 구조화 (메시지 순서대로. open_items가 앞 라벨에 의존)
    system = teacher_system(prompts.SYSTEM, "structure")
    for i, m in enumerate(msgs):
        if reaction_of[m.id].get("reaction") != "내용 있음":
            continue
        recent = msgs[max(0, i - recent_n):i]
        if m.user_reply_to and m.user_reply_to not in {r.id for r in recent} and m.user_reply_to in by_id:
            recent = [by_id[m.user_reply_to], *recent]
        user = prompts.structure(order["agenda"], order["form"], members, m, recent, list(open_items.values()),
                                 m.sent_at.date())
        raw = await claude.call("structure", system, user, log)
        entry = {"user": user, "raw": raw, "points": [], "problems": []}
        try:
            pts = json.loads(raw)["points"]
            entry["problems"] = check_points(pts, {r.id for r in [*recent, m]}, set(open_items))
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            pts, entry["problems"] = [], [f"JSON 문제: {e}"]
        if not entry["problems"]:
            for k, p in enumerate(pts, 1):
                pid = f"{m.id}-{k}"
                due = resolve_due(p.get("due_text"), m.sent_at.date()) if p.get("type") == "할 일" else None
                point = {**p, "id": pid, "speaker": m.member_id, "anonymous": m.anonymous,
                         "due": (due.isoformat() if due else p.get("due")), "msg_index": i}
                entry["points"].append(point)
                all_points.append(point)
                if p.get("answer_to") in open_items:
                    open_items.pop(p["answer_to"])
                if p["type"] in ("질문", "요청"):
                    open_items[pid] = OpenItem(id=pid, text=p["text"], speaker=names.get(m.member_id, "익명"))
        structure[m.id] = entry

    # 2. 묶음 (대화 끝 기준, 주장 포인트만)
    claims = [p for p in all_points if p["type"] in ("제안", "의견", "정보")]
    lines = "\n".join(
        f"- {p['id']}: {p['text']} (stance {p['stance']}, target {p.get('target')}, "
        f"{'익명' if p['anonymous'] else names.get(p['speaker'])})" for p in claims
    ) or "(없음)"
    cluster_user = f"[task] cluster\n안건: {order['agenda']}\n포인트:\n{lines}\n\n같은 말끼리 묶는다."
    clusters_raw = await claude.call("cluster", CLUSTER_SYSTEM, cluster_user, log) if claims else '{"clusters": []}'
    clusters = check_clusters(clusters_raw, {p["id"] for p in claims})

    # 3. 시점별 상황 요약 (현황판은 코드로 계산)
    summaries = []
    sys_summary = teacher_system(prompts.SYSTEM, "summary")
    for frac in CHECKPOINTS:
        cut = max(0, round(len(msgs) * frac) - 1)
        board = compute_board_at(cut, all_points, clusters, dialog, names)
        user = prompts.summary(order["agenda"], board)
        raw = await claude.call("summary", sys_summary, user, log)
        summaries.append({"at": frac, "until": msgs[cut].id, "board": board.model_dump(mode="json"),
                          "user": user, "raw": raw})

    return {"structure": structure, "clusters": clusters, "cluster_user": cluster_user, "summaries": summaries}


def check_clusters(raw: str, claim_ids: set[str]) -> dict:
    """묶음 라벨 형식 검사. 관계 값이 없거나 이상한 포인트, 없는 포인트 ID는 빼고 problems에 남긴다."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return {"clusters": [], "off_topic": [], "problems": [f"JSON 문제: {e}"]}
    problems, clean, seen = [], [], set()
    for c in data.get("clusters") or []:
        pts = []
        for x in c.get("points") or []:
            if not isinstance(x, dict) or x.get("id") not in claim_ids:
                problems.append(f"{c.get('id')}: 없는 포인트 {x}")
            elif x.get("relation") not in ("같음", "반대"):
                problems.append(f"{c.get('id')}: relation 값 {x.get('relation')} ({x.get('id')})")
            elif x["id"] in seen:
                problems.append(f"{c.get('id')}: 포인트 중복 {x['id']}")
            else:
                seen.add(x["id"])
                pts.append({"id": x["id"], "relation": x["relation"]})
        if pts:
            clean.append({"id": c.get("id") or f"c{len(clean) + 1}", "points": pts})
    return {"clusters": clean, "off_topic": data.get("off_topic") or [], "problems": problems}


def compute_board_at(cut: int, all_points: list[dict], clusters: dict, dialog: dict, names: dict) -> BoardResponse:
    pts = [p for p in all_points if p["msg_index"] <= cut]
    keep = {p["id"] for p in pts}
    points = [
        board_rules.Point(
            id=p["id"], text=p["text"], type=p["type"], stance=p["stance"], speaker=names.get(p["speaker"], p["speaker"]),
            evidence=tuple(p["evidence"]), anonymous=p["anonymous"], reason=p.get("reason"), target=p.get("target"),
            owner=names.get(p.get("owner"), p.get("owner")), due=p.get("due"),
        )
        for p in pts
    ]
    cl = [
        board_rules.Cluster(c["id"], tuple(board_rules.ClusterPoint(x["id"], x["relation"])
                                           for x in c.get("points", []) if x.get("id") in keep))
        for c in clusters.get("clusters", [])
    ]
    msgs = dialog["messages"][:cut + 1]
    reactions = [
        board_rules.Reaction(id=m["id"], speaker=names.get(m["speaker"], m["speaker"]), reaction=m["reaction"],
                             reply_to=m.get("reply_to"), reply_confidence=1.0, anonymous=bool(m.get("anonymous")))
        for m in msgs if m.get("reaction") in ("동의", "반대", "확인")
    ]
    board = BoardResponse.from_domain(board_rules.compute_board(points, [c for c in cl if c.points], reactions))
    # 임시: 현황판 코드가 answer_to로 답 판정을 하기 전까지 (PR #4 리뷰 요청), 답이 달린 질문·요청은 여기서 뺀다
    answered = {p["answer_to"] for p in pts if p.get("answer_to")}
    board.need_check = [i for i in board.need_check if i.id not in answered]
    return board
