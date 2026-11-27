"""주문서 → 가상 회의 대화 (Gemini).

Gemini가 같이 내는 것 (주문서를 아는 쪽이 붙여야 정확함):
messages(+ reaction, reply_to, user_reply_to), intended_points, stages, outcome
"""
import json

SYSTEM = """너는 한국 대학생, 직장인 팀의 채팅방 대화를 그대로 재현하는 작가다.
규칙:
- 실제 카카오톡, 슬랙처럼 쓴다. 맞춤법을 일부러 틀리지 않되 구어체, 줄임말, ㅋㅋ, ㅇㅋ를 자연스럽게 섞는다.
- AI로 정리한 긴 글은 AI가 쓴 티가 나게 쓴다 (번호 목록, 소제목, "정리해봤어요!" 같은 시작).
- 주문서의 인원, 메시지 수, 길이 비율, 넣을 상황, 결말을 반드시 지킨다.
- 사람마다 성격(persona)대로 말한다.
- 메시지 시간은 opened_at부터 days 안에서, 몇 분~몇 시간 간격으로 흐른다.
- 반드시 지정된 JSON 하나만 출력한다."""

LABEL_RULES = """메시지마다 붙일 라벨:
- reaction: 내용 있음 / 동의 / 반대 / 확인 / 잡담
  - 잡담 = 현황판에 올릴 안건 내용이 없는 메시지 (농담, 웃음, 진행 발언 "자유롭게 의견 주세요", 쪼개진 꼬리 줄)
  - "저도요", "ㅇㅋ", "좋아요", "+1" → 동의. "ㄴㄴ", "그건 좀.." → 반대
  - "넵", "알겠습니다" → 앞 메시지가 할 일이나 공지면 확인, 제안이나 의견이면 동의
  - 입장이 들어 있으면 짧아도 내용 있음 ("ㅋㅋ 또 기능 추가요?")
  - 실제로 할 일을 시키는 말은 내용 있음 ("누가 자료 좀 찾아봐 주세요")
- reply_to: 동의, 반대, 확인이면 대상 메시지 ID. 어느 메시지인지 모를 때만 null. 대상 메시지에 포인트가 여러 개여도 그 메시지 ID
- user_reply_to: 답장 기능을 쓴 메시지만 대상 메시지 ID, 아니면 null. 동의, 반대, 확인이고 user_reply_to가 있으면 reply_to도 같은 값
- anonymous: Pubble에게만 말하기면 true (채팅에는 안 보임)"""

OUTPUT = """출력 형식:
{"messages": [{"id": "msg_1", "speaker": "u1", "anonymous": false, "time": "YYYY-MM-DDTHH:MM", "text": "...",
               "reaction": "내용 있음", "reply_to": null, "user_reply_to": null}],
 "intended_points": [{"speaker": "u1", "point": "의도한 주장 한 줄", "message_ids": ["msg_1"]}],
 "stages": [{"from": "msg_1", "to": "msg_12", "stage": "의견 수집 / 정리 중 / 교착 / 수렴 / 결론 준비 / 이탈 중 하나"}],
 "outcome": {"decision": {"text": "...", "evidence": ["msg_id"]} 또는 null,
             "todos": [{"task": "...", "owner": "u1", "due_text": "...", "evidence": ["msg_id"]}],
             "open_issues": [{"text": "...", "evidence": ["msg_id"]}]}}
메시지 ID는 msg_1부터 순서대로. speaker는 팀원 id."""


def prompt(order: dict) -> str:
    members = "\n".join(f"- {m['id']} {m['name']}: {m['persona']}" for m in order["members"])
    situations = "\n".join(f"- {s}" for s in order["situations"])
    mix = ", ".join(f"{k} 약 {v}%" for k, v in order["length_mix"].items())
    anon = "Pubble에게만 말하기(익명) 메시지를 2~4개 넣는다." if order["anonymous"] else "익명 메시지는 넣지 않는다."
    return f"""주문서
- 안건: {order['agenda']} (형태: {order['form']}, 종류: {order['kind']})
- 팀원 ({len(order['members'])}명):
{members}
- 메시지 수: {order['n_messages']}개 (±5)
- 길이 비율: {mix}
- 기간: {order['days']}일, 시작 {order['opened_at']}, 안건 마감 {order['deadline']}
- 넣을 상황:
{situations}
- 답장 기능 사용: 메시지의 약 {order['reply_ratio']}%
- {anon}
- 결말: {order['ending']}

{LABEL_RULES}

{OUTPUT}"""


def continue_prompt(order: dict, dialog: dict) -> str:
    """짧게 끝난 대화를 이어 쓰게 한다. 마무리 라벨은 대화 전체 기준으로 다시 받는다."""
    msgs = dialog["messages"]
    remaining = max(order["n_messages"] - len(msgs), 5)
    so_far = json.dumps(msgs, ensure_ascii=False)
    return f"""{prompt(order)}

지금까지 쓴 대화 (메시지 {len(msgs)}개):
{so_far}

대화가 주문서보다 짧다. msg_{len(msgs) + 1}부터 이어서 메시지 {remaining}개를 더 쓴다.
- 앞 대화와 자연스럽게 이어지고, 주문서의 넣을 상황 중 아직 안 나온 것을 넣고, 결말에 맞게 마무리한다.
- messages에는 새로 쓴 메시지만 넣는다.
- intended_points, stages, outcome은 앞 대화까지 포함한 대화 전체 기준으로 다시 쓴다."""


def merge(dialog: dict, more: dict) -> dict:
    """이어 쓴 메시지를 붙이고, 마무리 라벨은 새 것으로 바꾼다. ID가 겹치면 뒤 번호로 다시 매긴다."""
    msgs = list(dialog["messages"])
    ids = {m["id"] for m in msgs}
    renamed = {}
    for m in more.get("messages") or []:
        new_id = m["id"] if m["id"] not in ids else f"msg_{len(msgs) + 1}"
        renamed[m["id"]] = new_id
        msgs.append({**m, "id": new_id})
        ids.add(new_id)
    for m in msgs[len(dialog["messages"]):]:
        for k in ("reply_to", "user_reply_to"):
            if m.get(k) in renamed and m.get(k) not in {x["id"] for x in dialog["messages"]}:
                m[k] = renamed[m[k]]
    out = {**dialog, "messages": msgs}
    for k in ("intended_points", "stages", "outcome"):
        if more.get(k):
            out[k] = more[k]
    return out


def too_short(order: dict, dialog: dict) -> bool:
    return len(dialog.get("messages") or []) < order["n_messages"] - 15


def check(order: dict, dialog: dict) -> list[str]:
    """형식 검사. 문제 목록 (비면 통과)."""
    problems = []
    msgs = dialog.get("messages")
    if not isinstance(msgs, list) or not msgs:
        return ["messages 없음"]
    ids = [m.get("id") for m in msgs]
    if len(set(ids)) != len(ids):
        problems.append("메시지 ID 중복")
    members = {m["id"] for m in order["members"]}
    reactions = {"내용 있음", "동의", "반대", "확인", "잡담"}
    for m in msgs:
        if m.get("speaker") not in members:
            problems.append(f"{m.get('id')}: 팀원 아닌 speaker {m.get('speaker')}")
        if m.get("reaction") not in reactions:
            problems.append(f"{m.get('id')}: reaction 값 {m.get('reaction')}")
        for k in ("reply_to", "user_reply_to"):
            if m.get(k) is not None and m.get(k) not in ids:
                problems.append(f"{m.get('id')}: {k}가 없는 메시지 {m.get(k)}")
    if too_short(order, dialog) or len(msgs) > order["n_messages"] + 15:
        problems.append(f"메시지 수 {len(msgs)} (주문 {order['n_messages']})")
    return problems


def parse(raw: str) -> dict:
    return json.loads(raw)
