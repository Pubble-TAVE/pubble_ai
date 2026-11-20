"""상대 날짜 표현 → 실제 마감 날짜 (규칙).

LLM이 날짜 계산을 틀리기 쉬워서, 마감 원문 표현(due_text)을 받아 코드로 다시 계산한다.
규칙 (task 목록 v1): "담주까지" = 다음 주 일요일. 한 주는 월~일.
못 읽는 표현이면 None → LLM이 낸 날짜를 그대로 씀.
"""
import re
from datetime import date, timedelta

_WEEKDAYS = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}
_NEXT_WEEK = re.compile(r"(담주|다음\s*주|다음주|차주)")
_THIS_WEEK = re.compile(r"(이번\s*주|이번주|금주)")
_WEEKDAY = re.compile(r"([월화수목금토일])요일")
_DAY_OF_MONTH = re.compile(r"(\d{1,2})\s*일")


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def resolve_due(due_text: str | None, base: date) -> date | None:
    if not due_text:
        return None
    t = due_text.strip()

    if "오늘" in t:
        return base
    if "내일" in t:
        return base + timedelta(days=1)
    if "모레" in t:
        return base + timedelta(days=2)

    wd = _WEEKDAY.search(t)
    weekday = _WEEKDAYS[wd.group(1)] if wd else None

    if _NEXT_WEEK.search(t):
        start = _week_start(base) + timedelta(days=7)
        return start + timedelta(days=6 if weekday is None else weekday)
    if _THIS_WEEK.search(t):
        start = _week_start(base)
        return start + timedelta(days=6 if weekday is None else weekday)
    if weekday is not None:
        # 요일만 있으면 오늘 이후 가장 가까운 그 요일 (오늘 포함)
        return base + timedelta(days=(weekday - base.weekday()) % 7)

    m = _DAY_OF_MONTH.search(t)
    if m and "월" not in t:
        day = int(m.group(1))
        try:
            d = base.replace(day=day)
        except ValueError:
            return None
        if d < base:  # 이미 지난 날짜면 다음 달
            month = base.month % 12 + 1
            year = base.year + (1 if base.month == 12 else 0)
            try:
                d = date(year, month, day)
            except ValueError:
                return None
        return d
    return None
