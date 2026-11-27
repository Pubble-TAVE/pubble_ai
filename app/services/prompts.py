"""task별 user 프롬프트. 선생 LLM(Claude)과 자체 모델(Qwen3-1.7B)이 같은 프롬프트를 쓴다.

학습 데이터의 입력도 이 형식 그대로 만든다 (형식이 다르면 학습한 게 안 맞음).
작성 기준과 예시는 선생에게만 system으로 붙인다 (teacher_guides.py).
"""
import json
from datetime import date

from app.schemas.board import BoardResponse
from app.schemas.common import AssignedTodo, Member, Message

_WEEKDAY_KO = "월화수목금토일"

SYSTEM = """너는 팀 채팅방의 회의 진행 도우미 Pubble이다.
규칙:
- 대화와 현황판에 있는 내용만 쓴다. 없는 사실, 숫자, 담당자, 날짜를 지어내지 않는다.
- 근거(evidence)에는 입력에 있는 ID만 쓴다.
- '익명'으로 표시된 메시지는 누가 썼는지 추측하거나 이름을 쓰지 않는다.
- 반드시 지정된 JSON 형식 하나만 출력한다."""


def fmt_date(d: date) -> str:
    return f"{d.isoformat()} ({_WEEKDAY_KO[d.weekday()]})"


def fmt_messages(messages: list[Message], members: list[Member]) -> str:
    names = {m.id: m.name for m in members}
    lines = []
    for m in messages:
        who = "익명" if m.anonymous else names.get(m.member_id, "알 수 없음")
        reply = f" (↩ {m.user_reply_to}에 답장)" if m.user_reply_to else ""
        lines.append(f"[{m.id}] {who} ({m.sent_at.strftime('%m/%d %H:%M')}){reply}: {m.text}")
    return "\n".join(lines) if lines else "(없음)"


def fmt_members(members: list[Member]) -> str:
    return "\n".join(f"- {m.id}: {m.name}" for m in members)


def fmt_board(board: BoardResponse) -> str:
    """현황판을 칸별로. 항목 ID는 근거로 씀."""
    names = {"common": "공통", "split": "갈림", "new": "새로움", "need_check": "확인 필요", "todos": "할 일"}
    out = []
    for key, label in names.items():
        items = getattr(board, key)
        out.append(f"[{label}]")
        if not items:
            out.append("(없음)")
        for i in items:
            people = ", ".join(p.name for p in i.people)
            line = f"- {i.id}: {i.text} ({people})"
            if i.opponents:
                line += f" vs 반대 ({', '.join(p.name for p in i.opponents)})"
            if i.owner:
                line += f" / 담당 {i.owner}" + (f", 마감 {i.due}" if i.due else "")
            out.append(line)
    return "\n".join(out)


def structure(agenda, form, members, message, recent, open_items, now: date) -> str:
    items = "\n".join(f"- {o.id}: {o.text} ({o.speaker})" for o in open_items) or "(없음)"
    return f"""[task] structure
안건: {agenda}{f" ({form})" if form else ""}
기준 날짜: {fmt_date(now)}
팀원:
{fmt_members(members)}
답이 아직 없는 질문·요청:
{items}
앞 메시지:
{fmt_messages(recent, members)}
새 메시지:
{fmt_messages([message], members)}

새 메시지를 의견 단위(포인트)로 나눈다. 포인트가 없으면 빈 목록.
- type: 제안 / 의견 / 질문 / 요청 / 정보 / 할 일
- stance: text가 가리키는 안에 대한 말한 사람의 입장 (찬성 / 반대 / 조건부 / 없음)
- target: 무엇에 대한 말인지 주제 텍스트. 질문·요청은 받는 사람 이름 또는 "전원"
- 할 일이면 owner(팀원 ID), due_text(마감 원문 표현), due(YYYY-MM-DD)
- answer_to: 위 '답이 아직 없는 질문·요청' 중 이 포인트가 답한 것의 ID, 아니면 null
출력 형식:
{{"points": [{{"text": "...", "type": "...", "stance": "...", "reason": "..." 또는 null, "target": "..." 또는 null, "owner": "..." 또는 null, "due_text": "..." 또는 null, "due": "YYYY-MM-DD" 또는 null, "answer_to": "..." 또는 null, "evidence": ["msg_id"]}}]}}"""


def summary(agenda: str, board: BoardResponse) -> str:
    return f"""[task] summary
안건: {agenda}
현황판:
{fmt_board(board)}

지금 어디까지 왔고 무엇이 걸려 있는지 2~3문장으로 쓴다. evidence는 현황판 항목 ID.
출력 형식:
{{"sentences": [{{"text": "...", "evidence": ["항목 ID"]}}]}}"""


def conclusion(agenda, members, board: BoardResponse, messages, base_date: date,
               existing_todos: list[AssignedTodo]) -> str:
    existing = (
        "\n".join(f"- {t.id}: {t.task} (담당 {t.owner_id}, 마감 {t.due})" for t in existing_todos) or "(없음)"
    )
    return f"""[task] conclusion
안건: {agenda}
기준 날짜: {fmt_date(base_date)}
팀원:
{fmt_members(members)}
현황판:
{fmt_board(board)}
이미 할당된 할 일 (다시 등록하지 않음, 결론에 나오면 existing_todo_id로 표시):
{existing}
근거 메시지:
{fmt_messages(messages, members)}

쓸 것:
- decision: 합의된 결론 한 문장. 합의가 없으면 null.
- todos: 담당자가 정해진 할 일. 합의된 행동 제안("~하면 어떨까요?")도 할 일로 뽑는다.
  owner_id는 팀원 ID. due_text는 마감 원문 표현, due는 YYYY-MM-DD 또는 null.
  담당자가 없는 일은 todos가 아니라 open_issues에 쓴다.
- open_issues: 정해지지 않은 것.
- flow: 논의가 어떻게 흘러왔는지 3~5줄.
evidence는 근거 메시지 ID.
출력 형식:
{json.dumps({"decision": {"text": "...", "evidence": ["msg_id"]},
             "todos": [{"task": "...", "owner_id": "...", "due_text": "...", "due": "YYYY-MM-DD",
                        "evidence": ["msg_id"], "existing_todo_id": None}],
             "open_issues": [{"text": "...", "evidence": ["msg_id"]}],
             "flow": [{"text": "...", "evidence": ["msg_id"]}]}, ensure_ascii=False)}
(decision은 합의가 없으면 null, due_text와 due는 없으면 null)"""
