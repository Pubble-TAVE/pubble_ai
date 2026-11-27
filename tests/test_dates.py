from datetime import date

import pytest

from app.services.dates import resolve_due

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
