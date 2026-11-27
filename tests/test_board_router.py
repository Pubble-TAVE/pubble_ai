"""POST /board 엔드포인트 테스트. 모델도 LLM도 쓰지 않는다 (lifespan을 돌리지 않아 키가 없어도 된다)."""
from fastapi.testclient import TestClient

from app.main import app
from tests.test_board import v2_request_dict

client = TestClient(app)


def test_board_returns_five_cells():
    r = client.post("/board", json=v2_request_dict())
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"common", "split", "new", "need_check", "todos"}
    assert [i["id"] for i in body["common"]] == ["c1"]
    assert body["new"][0]["people"][0]["name"] == "익명 1"


def test_board_same_input_gives_same_output():
    a = client.post("/board", json=v2_request_dict()).json()
    b = client.post("/board", json=v2_request_dict()).json()
    assert a == b


def test_board_accepts_empty_input():
    r = client.post("/board", json={"points": []})
    assert r.status_code == 200
    assert all(r.json()[k] == [] for k in ("common", "split", "new", "need_check", "todos"))


def test_board_rejects_unknown_values():
    data = v2_request_dict()
    data["points"][0]["type"] = "감탄"
    assert client.post("/board", json=data).status_code == 422


def test_board_requires_points():
    assert client.post("/board", json={}).status_code == 422
