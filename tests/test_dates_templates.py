from datetime import date

import pytest

from app.services.dates import resolve_due
from app.templates import messages as tpl

BASE = date(2026, 11, 18)  # 수요일


@pytest.mark.parametrize("text,expected", [
    ("담주까지", date(2026, 11, 29)),
    ("다음 주 화요일까지", date(2026, 11, 24)),
    ("이번 주까지", date(2026, 11, 22)),
    ("금요일까지", date(2026, 11, 20)),
    ("내일", date(2026, 11, 19)),
    ("모레 저녁", date(2026, 11, 20)),
    ("21일까지", date(2026, 11, 21)),
    ("5일까지", date(2026, 12, 5)),
    ("언젠가", None),
    (None, None),
])
def test_resolve_due(text, expected):
    assert resolve_due(text, BASE) == expected


def test_templates():
    assert tpl.vote_opened("MT 대관 장소", ["홍대", "신촌"]) == "'MT 대관 장소' 투표가 열렸습니다. 선택지: 홍대, 신촌"
    assert "마감까지 1시간 남았습니다." in tpl.participation_nudge("규연", "MT 대관 장소", "1h")
    assert tpl.fmt_due(None) == "마감 없음"
