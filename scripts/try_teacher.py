"""선생 LLM(Claude Haiku 5.5)으로 task 3개를 예시 대화(MVP 범위 줄이기)에 돌려보는 스크립트.

    set -a; source .env; set +a
    python -m scripts.try_teacher                 # 3개 전부
    python -m scripts.try_teacher structure       # 하나만
    CLAUDE_EFFORT=medium python -m scripts.try_teacher   # effort 바꿔서 비교

대화 10개 테스트 전에 effort(low / medium)별 결과를 눈으로 비교하는 용도.
"""
import asyncio
import sys
from datetime import date, datetime, timedelta

from app.config import Settings, build_clients
from app.schemas.board import BoardResponse
from app.schemas.common import Member, Message
from app.schemas.write import ConclusionRequest, OpenItem, StructureRequest, SummaryRequest
from app.services.writer import Writer

SCOPE = dict(project_id="p1", chat_room_id="c1", agenda_id="a1")
MEMBERS = [Member(id=f"u{i}", name=n) for i, n in enumerate(["지민", "서연", "하준", "민재", "유진"], 1)]
T0 = datetime.fromisoformat("2026-11-24T21:00:00+09:00")
LINES = [
    ("msg_3", "u1", "GPT랑 정리해봤어요!\n1. 현황: 백엔드 CRUD 70%, 프론트 채팅 화면 완료, 딥러닝은 데이터 생성 중\n"
                    "2. 문제: 12/11까지 현황판 연결까지 하기엔 빠듯함\n3. 제안: 놓친 내용 요약은 MVP에서 빼고 점 표시만\n"
                    "4. 투표는 오픈소스 라이브러리 쓰면 하루면 될 듯\n5. 디자인 시안은 언제쯤 나올까요?\n"
                    "결론적으로 범위를 줄이는 게 맞다고 봅니다", None),
    ("msg_4", "u2", "저도 정리해봤는데요\n- 일정이 빠듯한 건 동의합니다\n"
                    "- 근데 놓친 내용 요약은 사용자 테스트에서 제일 체감되는 기능이라 빼면 아쉬워요\n"
                    "- 투표는 기명/무기명 선택 때문에 라이브러리로는 어려울 수 있어요. 커스텀 되면 OK\n"
                    "- 시안은 제가 금요일까지 1차 올릴게요", None),
    ("msg_6", "u4", "점 표시만 해도 충분할 듯요", "msg_3"),
    ("msg_7", "u5", "지금까지 정리하면 지민님은 범위 축소 + 점 표시, 서연님은 요약 유지네요. 저는 서연님 쪽이요", None),
]
MESSAGES = [
    Message(id=i, member_id=who, sent_at=T0 + timedelta(minutes=10 * n), text=text, user_reply_to=reply)
    for n, (i, who, text, reply) in enumerate(LINES, 1)
]
BOARD = BoardResponse.model_validate({
    "common": [{"id": "c2", "text": "12/11 일정이 빠듯함", "people": [{"name": "지민", "evidence": ["msg_3"]},
                                                              {"name": "서연", "evidence": ["msg_4"]}],
                "evidence": ["msg_3", "msg_4"]}],
    "split": [{"id": "c3", "text": "놓친 내용 요약 빼기",
               "people": [{"name": "지민", "evidence": ["msg_3"]}, {"name": "민재", "evidence": ["msg_6"]}],
               "opponents": [{"name": "서연", "evidence": ["msg_4"]}, {"name": "유진", "evidence": ["msg_7"]}],
               "evidence": ["msg_3", "msg_4", "msg_6", "msg_7"]}],
    "new": [], "need_check": [],
    "todos": [{"id": "msg_4-4", "text": "디자인 시안 1차", "people": [{"name": "서연", "evidence": ["msg_4"]}],
               "owner": "서연", "due": "2026-11-27", "evidence": ["msg_4"]}],
})


async def main(only: str | None):
    s = Settings()
    primary, fallback, conclusion = build_clients(s)
    w = Writer(primary, fallback, conclusion_client=conclusion)
    print(f"모델: {s.claude_model}, effort: {s.claude_effort}")
    jobs = {
        "structure": lambda: w.structure(StructureRequest(
            **SCOPE, agenda_title="12/11 체크포인트 전 MVP 범위 줄이기", agenda_form="선택", members=MEMBERS,
            message=MESSAGES[1], recent_messages=MESSAGES[:1],
            open_items=[OpenItem(id="msg_3-4", text="디자인 시안 언제 나오나", speaker="지민")],
            now=date(2026, 11, 24))),
        "summary": lambda: w.summary(SummaryRequest(**SCOPE, agenda_title="MVP 범위 줄이기", board=BOARD)),
        "conclusion": lambda: w.conclusion(ConclusionRequest(
            **SCOPE, agenda_title="MVP 범위 줄이기", members=MEMBERS, board=BOARD, evidence_messages=MESSAGES,
            base_date=date(2026, 11, 25))),
    }
    for task, job in jobs.items():
        if only and task != only:
            continue
        res = await job()
        print(f"\n===== {task} =====")
        print(res.model_dump_json(indent=2, exclude_none=True))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else None))
