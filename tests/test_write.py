from app.schemas.common import Source
from app.schemas.write import StructureRequest
from app.services.writer import Writer
from tests.conftest import BOARD, MEMBERS, SCOPE, FakeLLM, msg

SEORYEON = ("저도 정리해봤는데요\n- 일정이 빠듯한 건 동의합니다\n"
            "- 근데 놓친 내용 요약은 빼면 아쉬워요\n- 시안은 제가 금요일까지 1차 올릴게요")


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


# ---------- 구조화 ----------
def structure_body(**kw):
    body = {
        **SCOPE, "agenda_title": "MVP 범위 줄이기", "agenda_form": "선택", "members": MEMBERS,
        "message": msg("msg_4", "u2", SEORYEON),
        "recent_messages": [msg("msg_3", "u1", "디자인 시안은 언제쯤 나올까요?")],
        "open_items": [{"id": "msg_3-1", "text": "디자인 시안 언제 나오나", "speaker": "지민"}],
        "now": "2026-11-24",
    }
    body.update(kw)
    return body


def p(text, type_, stance, **kw):
    return {"text": text, "type": type_, "stance": stance, "reason": None, "target": None, "owner": None,
            "due_text": None, "due": None, "answer_to": None, "evidence": ["msg_4"], **kw}


def test_structure_rules(client, llm):
    llm.queue("structure", {"points": [
        p("12/11 일정이 빠듯함", "의견", "찬성", target="일정"),
        p("놓친 내용 요약 빼기", "의견", "반대", target="놓친 내용 요약"),
        p("디자인 시안 1차", "할 일", "없음", owner="u2", due_text="금요일까지", due="2026-11-30",
          answer_to="msg_3-1"),
        p("없는 근거", "정보", "없음", evidence=["msg_99"]),
    ]})
    r = client.post("/write/structure", json=structure_body()).json()
    pts = r["points"]
    assert r["status"] == "ok"
    assert [x["id"] for x in pts] == ["msg_4-1", "msg_4-2", "msg_4-3"]  # 포인트 ID는 코드가 붙임
    assert pts[2]["due"] == "2026-11-27"  # 금요일까지 = 11/27 (LLM 날짜보다 규칙 우선)
    assert pts[2]["answer_to"] == "msg_3-1"
    assert pts[0]["owner"] is None  # 할 일이 아니면 담당자 없음


def test_structure_answer_to_only_open_items(client, llm):
    llm.queue("structure", {"points": [p("시안 금요일", "정보", "없음", answer_to="msg_1-9")]})
    r = client.post("/write/structure", json=structure_body()).json()
    assert r["points"][0]["answer_to"] is None  # open_items에 없는 ID는 버림


def test_structure_todo_without_owner_is_request(client, llm):
    llm.queue("structure", {"points": [p("자료 찾기", "할 일", "없음", owner=None, target="전원")]})
    r = client.post("/write/structure", json=structure_body()).json()
    assert r["points"][0]["type"] == "요청"  # 맡은 사람이 없으면 요청


def test_structure_empty_is_ok(client, llm):
    llm.queue("structure", {"points": []})  # 진행 발언, 꼬리 줄
    r = client.post("/write/structure", json=structure_body(message=msg("msg_4", "u2", "자유롭게 의견 주세요"))).json()
    assert r["status"] == "ok" and r["points"] == []


def test_structure_bad_value_retries_then_fails(client, llm):
    llm.queue("structure", {"points": [p("x", "반대함", "찬성")]}, "JSON 아님")
    r = client.post("/write/structure", json=structure_body()).json()
    assert r["status"] == "failed" and r["attempts"] == 2


def test_structure_prompt_shows_reply(client, llm):
    llm.queue("structure", {"points": []})
    body = structure_body(message=msg("msg_6", "u3", "점 표시만 해도 충분할 듯요", reply="msg_3"))
    client.post("/write/structure", json=body)
    assert "(↩ msg_3에 답장)" in llm.calls[0]
    assert "msg_3-1: 디자인 시안 언제 나오나" in llm.calls[0]  # 답이 없는 질문 목록


# ---------- 상황 요약 ----------
def summary_body():
    return {**SCOPE, "agenda_title": "MVP 범위 줄이기", "board": BOARD}


def test_summary_evidence_is_board_items(client, llm):
    llm.queue("summary", {"sentences": [
        {"text": "MVP 범위를 줄이자는 데는 의견이 모였어요.", "evidence": ["c1"]},
        {"text": "놓친 내용 요약을 뺄지는 의견이 갈려 있어요.", "evidence": ["c3", "c99"]},
        {"text": "없는 항목", "evidence": ["c99"]},
    ]})
    r = client.post("/write/summary", json=summary_body()).json()
    assert r["status"] == "ok"
    assert [s["evidence"] for s in r["sentences"]] == [["c1"], ["c3"]]  # 현황판에 없는 ID는 버림
    assert "c3: 놓친 내용 요약 빼기 (지민) vs 반대 (서연)" in llm.calls[0]


def test_summary_failed(client, llm):
    llm.queue("summary", "깨짐", "또 깨짐")
    r = client.post("/write/summary", json=summary_body()).json()
    assert r["status"] == "failed"  # 백엔드는 이전 요약 유지


# ---------- 결론 ----------
def conclusion_body():
    return {
        **SCOPE, "agenda_title": "MVP 범위 줄이기", "members": MEMBERS, "board": BOARD,
        "evidence_messages": [
            msg("msg_3", "u1", "결론적으로 범위를 줄이는 게 맞다고 봅니다"),
            msg("msg_4", "u2", "시안은 제가 금요일까지 1차 올릴게요"),
            msg("msg_9", "u1", "토요일까지 각자 파트별로 정리해서 오면 어떨까요?"),
            msg("msg_10", "u2", "좋아요"),
        ],
        "base_date": "2026-11-25",
        "existing_todos": [{"id": "t1", "task": "디자인 시안 1차", "owner_id": "u2", "due": "2026-11-27"}],
    }


def test_conclusion_rules(client, llm):
    llm.queue("conclusion", {
        "decision": {"text": "MVP 범위 축소로 결정", "evidence": ["msg_3"]},
        "todos": [
            {"task": "디자인 시안 1차", "owner_id": "u2", "due_text": "금요일까지", "due": None,
             "evidence": ["msg_4"], "existing_todo_id": "t1"},
            {"task": "파트별 정리 공유", "owner_id": "u1", "due_text": "토요일까지", "due": None,
             "evidence": ["msg_9", "msg_10"], "existing_todo_id": None},
            {"task": "견적 받기", "owner_id": None, "due_text": None, "due": None, "evidence": ["msg_3"],
             "existing_todo_id": None},
        ],
        "open_issues": [{"text": "놓친 내용 요약 포함 여부 미정", "evidence": ["msg_4"]}],
        "flow": [{"text": "범위 축소 제안", "evidence": ["msg_3"]}],
    })
    r = client.post("/write/conclusion", json=conclusion_body()).json()
    d = r["draft"]
    assert r["status"] == "ok"
    assert d["todos"][0]["existing_todo_id"] == "t1"  # 이미 할당된 할 일은 ID로 표시
    assert d["todos"][1]["due"] == "2026-11-28"  # 토요일까지
    assert len(d["todos"]) == 2
    assert {"놓친 내용 요약 포함 여부 미정", "견적 받기"} == {x["text"] for x in d["open_issues"]}


def test_conclusion_no_agreement(client, llm):
    llm.queue("conclusion", {"decision": None, "todos": [],
                             "open_issues": [{"text": "범위", "evidence": ["msg_3"]}], "flow": []})
    r = client.post("/write/conclusion", json=conclusion_body()).json()
    assert r["status"] == "no_conclusion"


async def test_conclusion_uses_claude_even_when_local():
    local, claude = FakeLLM(Source.local), FakeLLM(Source.api)
    claude.queue("conclusion", {"decision": None, "todos": [], "open_issues": [], "flow": []})
    from app.schemas.write import ConclusionRequest

    r = await Writer(local, claude, conclusion_client=claude).conclusion(ConclusionRequest(**conclusion_body()))
    assert r.source == "api" and not local.calls


# ---------- 대체 모델 ----------
async def test_fallback_to_claude():
    local, claude = FakeLLM(Source.local), FakeLLM(Source.api)
    local.queue("structure", "깨진 출력", "또 깨짐")
    claude.queue("structure", {"points": [p("12/11 일정이 빠듯함", "의견", "찬성")]})
    r = await Writer(local, claude, max_retries=1).structure(StructureRequest(**structure_body()))
    assert r.status == "ok" and r.source == "api" and r.attempts == 3
