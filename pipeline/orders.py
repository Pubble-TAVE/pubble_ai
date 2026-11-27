"""주문서: 대화마다 무엇을 만들지 코드가 정한다 (v2 '무엇을 다양하게 만들지', '일부러 넣을 상황').

seed가 같으면 같은 주문서가 나온다 (다시 돌려도 같은 데이터 구성).
"""
import random
from datetime import datetime, timedelta

FORMS = [("아이디어 모으기", 40), ("선택", 20), ("진행 공유", 20), ("문제 해결", 20)]
KINDS = [("프로젝트/개발", 35), ("팀플/과제", 30), ("동아리 운영", 15), ("모임/행사", 12), ("생활", 8)]

AGENDAS = {
    "아이디어 모으기": ["MVP에 넣을 기능 후보", "서비스 이름 후보", "중간 발표 데모 구성", "동아리 신입 행사 기획",
                  "팀 프로젝트 주제 후보", "홍보 콘텐츠 아이디어"],
    "선택": ["MVP 범위 정하기", "소형 모델 1.7B vs 4B", "백엔드 프레임워크 선택", "발표 자료 툴 선택",
           "디자인 시안 A안 vs B안", "회의 정기 요일 정하기"],
    "진행 공유": ["이번 주 파트별 진행 상황", "중간 점검: 막힌 것과 요청", "배포 준비 상황 공유", "과제 분담 진행 상황"],
    "문제 해결": ["배포 후 로그인 오류", "일정이 밀린 파트 조정", "API 문서와 실제 응답이 다름",
              "데이터 라벨이 기준과 안 맞음", "회의 참여율이 낮음"],
}

NAMES = ["지민", "서연", "하준", "민재", "유진", "도윤", "수아", "예린", "현우", "채원", "시우", "다은"]
PERSONAS = ["AI로 정리한 긴 글을 자주 올림", "말이 많고 의견이 분명함", "조용하고 짧게 반응함",
            "중간에 입장을 바꿈", "질문을 자주 함", "일을 잘 맡음", "늦게 들어와서 앞을 놓침", "농담을 자주 함"]

SITUATIONS = [
    "여러 명이 AI로 정리한 10~20줄짜리 긴 글을 연달아 올림 (번호 목록, 소제목)",
    "다른 사람 의견을 모아 정리하는 글 (\"지금까지 정리하면 A님은 X, B님은 Y\") + 글쓴이 의견 한 줄",
    "같은 주장 반복 (교착)",
    "답이 안 달리는 질문",
    "반응 없는 새 아이디어",
    "끝까지 말 안 하는 사람",
    "직전 메시지에 포인트가 여러 개인데 \"ㅇㅋ\" \"좋아요\"만 다는 사람",
    "사람을 지목한 질문과 요청 (\"OO님 이거 언제 돼요?\", \"피그마 확인해주세요\")",
    "할 일 맡기와 상대 날짜 표현 (\"제가 담주까지 정리할게요\")",
    "요청하고 수락하는 흐름 (\"OO님 이거 해주세요\" → \"넵 제가 할게요\")",
    "행동 제안과 합의 (\"토요일까지 각자 정리해서 오면 어떨까요?\" → \"좋아요\")",
    "한 생각을 여러 줄로 나눠 보내기 (중간에 다른 사람이 끼어들기도 함)",
    "사람이 직접 하는 진행 발언 (\"자유롭게 의견 주세요\")",
    "답장 기능으로 특정 메시지에 답하기 (반대나 질문의 답에 많이)",
    "Pubble에게만 말하기(익명)로 의견 남기기",
    "Pubble 부르기 (\"@Pubble\", 의견이 섞인 부르기도)",
    "같은 안을 다르게 부르기 (예: 4B 모델 / 큰 쪽)",
    "안건과 관계없는 이야기로 잠깐 빠짐",
]
ENDINGS = [("결론과 할 일까지", 50), ("미결 사항이 남음", 30), ("결론 없이 끝남", 20)]


def _pick(rng: random.Random, weighted):
    items, weights = zip(*weighted)
    return rng.choices(items, weights=weights, k=1)[0]


def make_order(rng: random.Random, idx: int) -> dict:
    form = _pick(rng, FORMS)
    n_members = rng.randint(4, 8)
    names = rng.sample(NAMES, n_members)
    start = datetime(2026, 11, 2, 20, 0) + timedelta(days=rng.randint(0, 40), hours=rng.randint(-10, 3))
    return {
        "id": f"dlg_{idx:04d}",
        "form": form,
        "kind": _pick(rng, KINDS),
        "agenda": rng.choice(AGENDAS[form]),
        "members": [{"id": f"u{i + 1}", "name": n, "persona": rng.choice(PERSONAS)} for i, n in enumerate(names)],
        "n_messages": rng.randint(50, 100),
        "length_mix": {"긴 정리글(10줄 이상)": 20, "중간 글(2~5줄)": 50, "짧은 반응·잡담": 30},
        "days": rng.randint(1, 3),
        "opened_at": start.isoformat(timespec="minutes"),
        "deadline": (start + timedelta(days=1)).isoformat(timespec="minutes"),
        "situations": rng.sample(SITUATIONS, rng.randint(2, 4)),
        "ending": _pick(rng, ENDINGS),
        "reply_ratio": rng.choice([10, 20, 30, 40]),
        "anonymous": rng.random() < 0.15,
    }


def make_orders(n: int, seed: int = 0, start: int = 1) -> list[dict]:
    rng = random.Random(seed)
    return [make_order(rng, start + i) for i in range(n)]
