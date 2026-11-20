from app.schemas.common import Source
from app.services.writer import Writer
from tests.conftest import MEMBERS, OPTIONS, SCOPE, FakeLLM, msg


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


# ---------- board_summary ----------
def board_body():
    return {
        **SCOPE, "agenda_title": "MT 대관 장소", "options": OPTIONS, "members": MEMBERS,
        "counts": [{"option_id": "o1", "count": 1}, {"option_id": "o2", "count": 2}],
        "messages": [
            msg("m1", "u1", "신촌이 교통이 낫겠네요"),
            msg("m2", "u2", "홍대가 가게 많아요"),
            msg("m3", "u3", "솔직히 홍대 너무 비쌈", anonymous=True),
        ],
    }


def test_board_summary_drops_anonymous_and_unknown_ids(client, llm):
    llm.queue("board_summary", {
        "issues": [{"text": "교통 vs 가게 수", "evidence": ["m1", "m2", "m3"]}],
        "agreements": [{"text": "없는 근거", "evidence": ["m99"]}],
    })
    r = client.post("/write/board-summary", json=board_body()).json()
    assert r["status"] == "ok"
    assert r["issues"][0]["evidence"] == ["m1", "m2"]  # 익명(m3)은 근거에서 빠짐
    assert r["agreements"] == []  # 입력에 없는 ID만 있으면 버림
    assert "솔직히 홍대 너무 비쌈" not in llm.calls[0]  # 프롬프트에도 안 들어감


def test_board_summary_retries_then_fails(client, llm):
    llm.queue("board_summary", "JSON 아님", {"issues": [{"text": "x", "evidence": ["nope"]}]})
    r = client.post("/write/board-summary", json=board_body()).json()
    assert r["status"] == "failed" and r["attempts"] == 2  # 백엔드는 이전 문장 유지


# ---------- conclusion ----------
def conclusion_body(**kw):
    body = {
        **SCOPE, "agenda_title": "MT 대관 장소", "options": OPTIONS, "members": MEMBERS,
        "counts": [{"option_id": "o2", "count": 3}],
        "messages": [
            msg("m1", "u1", "신촌으로 하죠"),
            msg("m2", "u3", "예약은 제가 담주까지 할게요"),
            msg("m3", "u2", "예산은 아직 모르겠네요"),
            msg("m4", "u2", "견적은 누가 받죠?"),
        ],
        "base_date": "2026-11-18",
        "assigned_todos": [{"id": "t1", "task": "신촌 대관 예약", "owner_id": "u3", "due": "2026-11-29"}],
    }
    body.update(kw)
    return body


def test_conclusion_rules(client, llm):
    llm.queue("conclusion", {
        "decision": {"text": "신촌으로 결정", "evidence": ["m1"]},
        "todos": [
            {"task": "신촌 대관 예약", "owner_id": "u3", "due_text": "담주까지", "due": "2026-11-25",
             "evidence": ["m2"], "existing_todo_id": "t1"},
            {"task": "견적 받기", "owner_id": None, "due_text": None, "due": None, "evidence": ["m4"],
             "existing_todo_id": None},
        ],
        "open_issues": [{"text": "예산", "evidence": ["m3"]}],
        "flow": [{"text": "처음부터 신촌 쪽으로 모임", "evidence": ["m1"]}],
    })
    r = client.post("/write/conclusion", json=conclusion_body()).json()
    d = r["draft"]
    assert r["status"] == "ok"
    assert d["todos"][0]["existing_todo_id"] == "t1"  # 이미 할당된 할 일은 ID로 표시
    assert d["todos"][0]["due"] == "2026-11-29"  # "담주까지" = 다음 주 일요일 (LLM 날짜보다 규칙 우선)
    assert len(d["todos"]) == 1
    assert {"예산", "견적 받기"} == {x["text"] for x in d["open_issues"]}  # 담당자 없는 일은 미결 사항으로


def test_conclusion_no_agreement(client, llm):
    llm.queue("conclusion", {"decision": None, "todos": [], "open_issues": [{"text": "장소", "evidence": ["m1"]}],
                             "flow": []})
    r = client.post("/write/conclusion", json=conclusion_body()).json()
    assert r["status"] == "no_conclusion"


def test_conclusion_revision_prompt(client, llm):
    llm.queue("conclusion", {"decision": {"text": "신촌", "evidence": ["m1"]}, "todos": [], "open_issues": [],
                             "flow": []})
    prev = {"decision": {"text": "홍대", "evidence": ["m1"]}, "todos": [], "open_issues": [], "flow": []}
    client.post("/write/conclusion", json=conclusion_body(previous_draft=prev, revision_request="장소를 신촌으로"))
    assert "수정 요청: 장소를 신촌으로" in llm.calls[0]


# ---------- option_normalize ----------
def test_option_normalize_matches_by_name(client, llm):
    llm.queue("option_normalize", {"name": "홍대", "matched_option_id": None})
    body = {**SCOPE, "agenda_title": "MT 대관 장소", "message": msg("m5", "u1", "홍대 쪽 어때요?"),
            "options": OPTIONS}
    r = client.post("/write/option-normalize", json=body).json()
    assert r["matched_option_id"] == "o1" and r["evidence"] == ["m5"]


# ---------- todo_catch ----------
def todo_body(text="그럼 제가 담주까지 견적 받아올게요"):
    return {**SCOPE, "message": msg("m7", "u1", text), "members": MEMBERS}


def test_todo_catch_ok(client, llm):
    llm.queue("todo_catch", {"task": "견적 받기", "owner_id": "u1", "due_text": "담주까지", "due": None,
                             "evidence": ["m7"]})
    r = client.post("/write/todo-catch", json=todo_body()).json()
    assert r["status"] == "ok" and r["todo"]["due"] == "2026-11-29"
    assert r["display_text"] == "해원님에게 할 일 요청이 있습니다. 견적 받기 (마감 11/29(일))"


def test_todo_catch_no_owner_skipped(client, llm):
    llm.queue("todo_catch", {"task": "견적 받기", "owner_id": None, "due_text": None, "due": None,
                             "evidence": ["m7"]})
    r = client.post("/write/todo-catch", json=todo_body("견적 누가 받아야 할 듯")).json()
    assert r["status"] == "skipped" and r["todo"] is None


# ---------- next_agenda ----------
def test_next_agenda_dedup_and_room(client, llm):
    llm.queue("next_agenda", {"candidates": [
        {"title": "예산", "reason": "미결", "evidence": ["m3"]},
        {"title": "회비 금액", "reason": "이미 있음", "evidence": ["m3"]},
    ]})
    body = {**SCOPE, "open_issues": [{"text": "예산", "evidence": ["m3"]}],
            "other_agenda_messages": [], "existing_agendas": ["회비 금액"]}
    r = client.post("/write/next-agenda", json=body).json()
    assert [c["title"] for c in r["candidates"]] == ["예산"]
    assert r["candidates"][0]["chat_room_id"] == "c1"


# ---------- 대체 모델 ----------
async def test_fallback_to_api():
    local, api = FakeLLM(Source.local), FakeLLM(Source.api)
    local.queue("option_normalize", "깨진 출력", "또 깨짐")
    api.queue("option_normalize", {"name": "건대", "matched_option_id": None})
    from app.schemas.write import OptionNormalizeRequest

    req = OptionNormalizeRequest(**SCOPE, agenda_title="장소", message=msg("m1", "u1", "건대 어때요"), options=OPTIONS)
    r = await Writer(local, api, max_retries=1).option_normalize(req)
    assert r.status == "ok" and r.source == "api" and r.attempts == 3 and r.matched_option_id is None
