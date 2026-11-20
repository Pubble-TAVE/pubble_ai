"""task별 프롬프트. 선생 LLM(OpenAI)과 자체 모델(Qwen3-1.7B)이 같은 프롬프트를 쓴다.

학습 데이터의 입력도 이 형식 그대로 만든다 (형식이 다르면 학습한 게 안 맞음).
"""
import json
from datetime import date

from app.schemas.common import Member, Message, Option, OptionCount

_WEEKDAY_KO = "월화수목금토일"

SYSTEM = """너는 팀 채팅방의 회의 진행 도우미 Pubble이다.
규칙:
- 대화에 있는 내용만 쓴다. 없는 사실, 숫자, 담당자, 날짜를 지어내지 않는다.
- 모든 문장에 근거가 되는 메시지 ID를 evidence로 붙인다. 입력에 있는 ID만 쓴다.
- '익명'으로 표시된 메시지는 누가 썼는지 추측하거나 이름을 쓰지 않는다.
- 문장은 짧은 명사형/개조식으로 쓴다.
- 반드시 지정된 JSON 형식 하나만 출력한다."""


def fmt_date(d: date) -> str:
    return f"{d.isoformat()} ({_WEEKDAY_KO[d.weekday()]})"


def fmt_messages(messages: list[Message], members: list[Member]) -> str:
    names = {m.id: m.name for m in members}
    lines = []
    for m in messages:
        who = "익명" if m.anonymous else names.get(m.member_id, "알 수 없음")
        lines.append(f"[{m.id}] {who} ({m.sent_at.strftime('%m/%d %H:%M')}): {m.text}")
    return "\n".join(lines) if lines else "(없음)"


def fmt_options(options: list[Option], counts: list[OptionCount] | None = None) -> str:
    c = {x.option_id: x.count for x in counts or []}
    return "\n".join(
        f"- {o.id}: {o.name}" + (f" ({c.get(o.id, 0)}명)" if counts is not None else "") for o in options
    ) or "(없음)"


def fmt_members(members: list[Member]) -> str:
    return "\n".join(f"- {m.id}: {m.name}" for m in members)


def board_summary(agenda: str, options, counts, messages, members) -> str:
    return f"""[task] board_summary
안건: {agenda}
선택지와 지지 인원 (숫자는 이미 계산됨, 문장에 숫자를 새로 만들지 말 것):
{fmt_options(options, counts)}
최근 메시지:
{fmt_messages(messages, members)}

쟁점(의견이 왜 갈리는지)과 합의(다들 동의한 부분)를 각각 0~3개 쓴다.
출력 형식:
{{"issues": [{{"text": "...", "evidence": ["msg_id"]}}], "agreements": [{{"text": "...", "evidence": ["msg_id"]}}]}}"""


def conclusion(
    agenda, options, counts, vote_result, messages, members, base_date, assigned_todos, previous_draft, revision
) -> str:
    vote = fmt_options(options, vote_result) if vote_result else "(투표 안 함)"
    assigned = (
        "\n".join(f"- {t.id}: {t.task} (담당 {t.owner_id}, 마감 {t.due})" for t in assigned_todos)
        or "(없음)"
    )
    revise = ""
    if previous_draft is not None:
        revise = f"""
이전 결론 초안:
{json.dumps(previous_draft, ensure_ascii=False)}
수정 요청: {revision or "(내용 없음)"}
수정 요청을 반영해 다시 쓴다. 요청과 관계없는 부분은 유지한다.
"""
    return f"""[task] conclusion
안건: {agenda}
기준 날짜: {fmt_date(base_date)}
팀원:
{fmt_members(members)}
선택지와 지지 인원:
{fmt_options(options, counts)}
투표 결과:
{vote}
이미 할당된 할 일 (다시 등록하지 않음, 결론에 나오면 existing_todo_id로 표시):
{assigned}
전체 메시지:
{fmt_messages(messages, members)}
{revise}
쓸 것:
- decision: 합의된 결론 한 문장. 합의가 없으면 null.
- todos: 담당자가 정해진 할 일만. owner_id는 팀원 ID. due_text는 마감 원문 표현(예: "담주까지"), due는 YYYY-MM-DD 또는 null.
  담당자가 없는 일은 todos가 아니라 open_issues에 쓴다.
- open_issues: 정해지지 않은 것.
- flow: 논의가 어떻게 흘러왔는지 3~5줄.
출력 형식:
{{"decision": {{"text": "...", "evidence": ["msg_id"]}} 또는 null,
 "todos": [{{"task": "...", "owner_id": "...", "due_text": "..." 또는 null, "due": "YYYY-MM-DD" 또는 null, "evidence": ["msg_id"], "existing_todo_id": "..." 또는 null}}],
 "open_issues": [{{"text": "...", "evidence": ["msg_id"]}}],
 "flow": [{{"text": "...", "evidence": ["msg_id"]}}]}}"""


def option_normalize(agenda, message, options, members) -> str:
    return f"""[task] option_normalize
안건: {agenda}
기존 선택지:
{fmt_options(options)}
제안 메시지:
{fmt_messages([message], members)}

제안된 선택지 이름을 짧게 정리한다 (예: "홍대 쪽 어때요?" → "홍대").
기존 선택지와 같은 것이면 matched_option_id에 그 ID, 새 선택지면 null.
출력 형식: {{"name": "...", "matched_option_id": "..." 또는 null}}"""


def todo_catch(message, previous, members, base_date: date) -> str:
    msgs = [previous, message] if previous else [message]
    return f"""[task] todo_catch
기준 날짜: {fmt_date(base_date)}
팀원:
{fmt_members(members)}
메시지 (마지막이 할 일 메시지):
{fmt_messages(msgs, members)}

마지막 메시지의 할 일을 뽑는다. "제가 할게요"면 보낸 사람이 담당자.
담당자를 알 수 없으면 owner_id는 null.
출력 형식: {{"task": "...", "owner_id": "..." 또는 null, "due_text": "..." 또는 null, "due": "YYYY-MM-DD" 또는 null, "evidence": ["msg_id"]}}"""


def next_agenda(open_issues, other_msgs, existing_candidates, existing_agendas, members) -> str:
    issues = "\n".join(f"- {x.text} (근거: {', '.join(x.evidence)})" for x in open_issues) or "(없음)"
    cands = "\n".join(f"- {x}" for x in existing_candidates) or "(없음)"
    agendas = "\n".join(f"- {x}" for x in existing_agendas) or "(없음)"
    return f"""[task] next_agenda
미결 사항:
{issues}
다른 안건 얘기로 분류된 메시지:
{fmt_messages(other_msgs, members)}
이미 있는 후보 (겹치면 만들지 않음):
{cands}
이미 있는 안건 (겹치면 만들지 않음):
{agendas}

다음에 이야기할 안건 후보를 0~3개 쓴다. 제목은 짧게, 이유는 한 줄.
출력 형식: {{"candidates": [{{"title": "...", "reason": "...", "evidence": ["msg_id"]}}]}}"""
