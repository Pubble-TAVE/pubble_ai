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


MEMBERS = [{"id": "u1", "name": "해원"}, {"id": "u2", "name": "정은"}, {"id": "u3", "name": "지현"}]
OPTIONS = [{"id": "o1", "name": "홍대"}, {"id": "o2", "name": "신촌"}]
SCOPE = {"project_id": "p1", "chat_room_id": "c1", "agenda_id": "a1"}


def msg(i, member, text, anonymous=False, at="2026-11-18T21:10:00+09:00"):
    return {"id": i, "member_id": member, "sent_at": at, "text": text, "anonymous": anonymous}
