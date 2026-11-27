import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.common import Source
from app.services.writer import Writer


class FakeLLM:
    """task별로 정해둔 답을 차례로 돌려주는 가짜 LLM."""

    def __init__(self, source=Source.api):
        self.source = source
        self.answers: dict[str, list] = {}
        self.calls: list[str] = []
        self.systems: list[str] = []

    def queue(self, task: str, *answers):
        self.answers.setdefault(task, []).extend(answers)

    async def complete(self, system: str, user: str) -> str:
        task = user.split("\n", 1)[0].replace("[task] ", "").strip()
        self.calls.append(user)
        self.systems.append(system)
        a = self.answers[task].pop(0)
        if isinstance(a, Exception):
            raise a
        return a if isinstance(a, str) else json.dumps(a, ensure_ascii=False)


@pytest.fixture
def llm():
    return FakeLLM()


@pytest.fixture
def client(llm):
    app.state.writer = Writer(llm, fallback=None, max_retries=1)
    with TestClient(app) as c:
        yield c
    del app.state.writer


MEMBERS = [{"id": "u1", "name": "지민"}, {"id": "u2", "name": "서연"}, {"id": "u3", "name": "하준"}]
SCOPE = {"project_id": "p1", "chat_room_id": "c1", "agenda_id": "a1"}


def msg(i, member, text, anonymous=False, reply=None, at="2026-11-24T21:10:00+09:00"):
    return {"id": i, "member_id": member, "sent_at": at, "text": text, "anonymous": anonymous, "user_reply_to": reply}


def item(i, text, people, opponents=(), owner=None, due=None, evidence=()):
    p = lambda n: {"name": n, "reason": None, "evidence": list(evidence)}  # noqa: E731
    return {"id": i, "text": text, "people": [p(n) for n in people], "opponents": [p(n) for n in opponents],
            "owner": owner, "due": due, "evidence": list(evidence)}


BOARD = {
    "common": [item("c1", "MVP 범위 줄이기", ["지민", "하준"], evidence=["msg_3", "msg_8"])],
    "split": [item("c3", "놓친 내용 요약 빼기", ["지민"], ["서연"], evidence=["msg_3", "msg_4"])],
    "new": [],
    "need_check": [],
    "todos": [item("msg_4-4", "디자인 시안 1차", ["서연"], owner="서연", due="2026-11-27", evidence=["msg_4"])],
}
