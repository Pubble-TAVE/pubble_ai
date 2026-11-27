"""데이터 파이프라인: 주문서, 형식 검사, 라벨 흐름(open_items, 시점별 현황판), 비용 계산."""
import json

from pipeline import generate
from pipeline.clients import Usage, UsageLog
from pipeline.cost import cost_of, report
from pipeline.label import check_clusters, label_dialog
from pipeline.orders import make_orders

ORDER = {
    "id": "dlg_0001", "form": "진행 공유", "kind": "프로젝트/개발", "agenda": "이번 주 진행 상황",
    "members": [{"id": "u1", "name": "지민", "persona": ""}, {"id": "u2", "name": "서연", "persona": ""},
                {"id": "u3", "name": "하준", "persona": ""}],
    "n_messages": 4, "anonymous": False,
}
DIALOG = {"messages": [
    {"id": "msg_1", "speaker": "u1", "time": "2026-11-24T21:00", "text": "디자인 시안 언제 나와요?",
     "reaction": "내용 있음", "reply_to": None, "user_reply_to": None},
    {"id": "msg_2", "speaker": "u2", "time": "2026-11-24T21:05", "text": "제가 금요일까지 올릴게요",
     "reaction": "내용 있음", "reply_to": None, "user_reply_to": "msg_1"},
    {"id": "msg_3", "speaker": "u3", "time": "2026-11-24T21:06", "text": "ㅇㅋ",
     "reaction": "동의", "reply_to": "msg_2", "user_reply_to": None},
    {"id": "msg_4", "speaker": "u1", "time": "2026-11-24T21:07", "text": "ㅋㅋ 배고프다",
     "reaction": "잡담", "reply_to": None, "user_reply_to": None},
]}


class FakeClaude:
    def __init__(self):
        self.users = []

    async def call(self, step, system, user, log):
        self.users.append((step, user))
        log.add(Usage(model="claude-haiku-5-5", step=step, input_tokens=1000, output_tokens=200))
        if step == "structure" and "[msg_1]" in user.split("새 메시지:")[1]:
            return json.dumps({"points": [{"text": "디자인 시안 언제 나오나", "type": "질문", "stance": "없음",
                                           "target": "전원", "evidence": ["msg_1"]}]})
        if step == "structure":
            return json.dumps({"points": [{"text": "디자인 시안 1차", "type": "할 일", "stance": "없음",
                                           "owner": "u2", "due_text": "금요일까지", "answer_to": "msg_1-1",
                                           "evidence": ["msg_2"]}]})
        return json.dumps({"sentences": [{"text": "시안은 서연님이 금요일까지 올려요.", "evidence": ["msg_2-1"]}]})


def test_orders_are_reproducible_and_in_range():
    a, b = make_orders(20, seed=1), make_orders(20, seed=1)
    assert a == b
    for o in a:
        assert 4 <= len(o["members"]) <= 8 and 50 <= o["n_messages"] <= 100
        assert 2 <= len(o["situations"]) <= 4
        assert "주문서" in generate.prompt(o)


def test_generate_check_finds_problems():
    bad = {"messages": [{"id": "msg_1", "speaker": "u9", "reaction": "좋음", "reply_to": "msg_7"}]}
    problems = generate.check(ORDER, bad)
    assert any("speaker" in p for p in problems) and any("reaction" in p for p in problems)
    assert any("reply_to" in p for p in problems)
    assert generate.check(ORDER, DIALOG) == []


async def test_label_flow():
    claude, log = FakeClaude(), UsageLog()
    labels = await label_dialog(ORDER, DIALOG, claude, log)
    s = labels["structure"]
    assert set(s) == {"msg_1", "msg_2"}  # 내용 있음만 구조화
    assert all(not e["problems"] for e in s.values())
    second = [u for step, u in claude.users if step == "structure"][1]
    assert "msg_1-1: 디자인 시안 언제 나오나 (지민)" in second  # 앞 라벨의 질문이 open_items로
    assert "(↩ msg_1에 답장)" in second
    todo = s["msg_2"]["points"][0]
    assert todo["id"] == "msg_2-1" and todo["due"] == "2026-11-27"  # 금요일까지
    last = labels["summaries"][-1]["board"]
    assert last["need_check"] == []  # 답이 달려서 확인 필요에서 빠짐 (현황판 규칙은 PR #4 기준)
    assert [t["owner"] for t in last["todos"]] == ["서연"]
    assert len(labels["summaries"]) == 4


def test_cost():
    u = Usage(model="claude-haiku-5-5", step="structure", input_tokens=1_000_000, output_tokens=1_000_000)
    assert round(cost_of(u), 2) == 0.60
    text = report([u], n_dialogs=1, target=300)
    assert "300개 예상" in text and "Batch" in text


def test_cluster_check_drops_bad_relation():
    raw = json.dumps({"clusters": [{"id": "c1", "points": [{"id": "msg_1-1", "relation": "같음"}, {"id": "msg_2-1"},
                                                        {"id": "msg_9-9", "relation": "같음"}]}]})
    out = check_clusters(raw, {"msg_1-1", "msg_2-1"})
    assert out["clusters"] == [{"id": "c1", "points": [{"id": "msg_1-1", "relation": "같음"}]}]
    assert len(out["problems"]) == 2


def test_continue_short_dialog():
    order = {**ORDER, "n_messages": 60}
    assert generate.too_short(order, DIALOG)
    assert "msg_5부터 이어서" in generate.continue_prompt(order, DIALOG)
    more = {"messages": [{"id": "msg_5", "speaker": "u2", "time": "2026-11-24T21:10", "text": "좋아요",
                          "reaction": "동의", "reply_to": "msg_2", "user_reply_to": None},
                         {"id": "msg_2", "speaker": "u3", "time": "2026-11-24T21:11", "text": "ㅇㅋ",
                          "reaction": "잡담", "reply_to": None, "user_reply_to": None}],
            "outcome": {"decision": None, "todos": [], "open_issues": []}}
    merged = generate.merge(DIALOG, more)
    assert [m["id"] for m in merged["messages"]] == ["msg_1", "msg_2", "msg_3", "msg_4", "msg_5", "msg_6"]
    assert merged["messages"][4]["reply_to"] == "msg_2"  # 앞 대화를 가리키는 건 그대로
    assert merged["outcome"] == more["outcome"]
