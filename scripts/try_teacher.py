"""선생 LLM(OpenAI)으로 task 5개를 예시 대화 하나에 돌려보는 스크립트.

    set -a; source .env; set +a
    python -m scripts.try_teacher            # 5개 전부
    python -m scripts.try_teacher conclusion  # 하나만

OPENAI_MODEL을 바꿔가며 돌려보고 결과를 비교하는 용도 (S3 정답 모델 결정).
"""
import asyncio
import sys
from datetime import date, datetime, timedelta

from app.config import Settings, build_clients
from app.schemas.common import Evidenced, Member, Message, Option, OptionCount
from app.schemas.write import (
    BoardSummaryRequest,
    ConclusionRequest,
    NextAgendaRequest,
    OptionNormalizeRequest,
    TodoCatchRequest,
)
from app.services.writer import Writer

SCOPE = dict(project_id="p1", chat_room_id="c1", agenda_id="a1")
MEMBERS = [Member(id=f"u{i}", name=n) for i, n in enumerate(["해원", "정은", "지현", "민지"], 1)]
OPTIONS = [Option(id="o1", name="홍대"), Option(id="o2", name="신촌")]
T0 = datetime.fromisoformat("2026-11-18T19:00:00+09:00")
LINES = [
    ("u1", "홍대 어때요? 가게 많아서"),
    ("u3", "신촌이 교통이 훨씬 나아요"),
    ("u2", "ㅋㅋ 홍대 또 가?"),
    ("u1", "생각해보니 신촌이 낫겠네요"),
    ("u4", "근데 뒤풀이는 어디서 해요?"),
    ("u2", "솔직히 홍대는 너무 비싸서 싫음", True),
    ("u3", "그럼 신촌으로 하고 예약은 제가 담주까지 할게요"),
    ("u2", "예산은 아직 모르겠네"),
]
MESSAGES = [
    Message(id=f"m{i}", member_id=who, sent_at=T0 + timedelta(minutes=10 * i), text=text,
            anonymous=bool(rest and rest[0]))
    for i, (who, text, *rest) in enumerate(LINES, 1)
]
COUNTS = [OptionCount(option_id="o1", count=1), OptionCount(option_id="o2", count=3)]


async def main(only: str | None):
    primary, fallback = build_clients(Settings())
    w = Writer(primary, fallback)
    jobs = {
        "board_summary": lambda: w.board_summary(BoardSummaryRequest(
            **SCOPE, agenda_title="MT 대관 장소", options=OPTIONS, members=MEMBERS, counts=COUNTS, messages=MESSAGES)),
        "conclusion": lambda: w.conclusion(ConclusionRequest(
            **SCOPE, agenda_title="MT 대관 장소", options=OPTIONS, members=MEMBERS, counts=COUNTS,
            messages=MESSAGES, base_date=date(2026, 11, 18))),
        "option_normalize": lambda: w.option_normalize(OptionNormalizeRequest(
            **SCOPE, agenda_title="MT 대관 장소", message=MESSAGES[0], options=OPTIONS[1:])),
        "todo_catch": lambda: w.todo_catch(TodoCatchRequest(
            **SCOPE, message=MESSAGES[6], previous_message=MESSAGES[5], members=MEMBERS)),
        "next_agenda": lambda: w.next_agenda(NextAgendaRequest(
            **SCOPE, open_issues=[Evidenced(text="예산 미정", evidence=["m8"])],
            other_agenda_messages=[MESSAGES[4]])),
    }
    for task, job in jobs.items():
        if only and task != only:
            continue
        res = await job()
        print(f"\n===== {task} =====")
        print(res.model_dump_json(indent=2, exclude_none=True))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else None))
