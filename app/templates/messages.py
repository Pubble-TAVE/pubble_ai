"""LLM 없이 정해진 문구 (템플릿).

선택기(연)가 행동을 고르면 AI 서버가 이름, 선택지를 채워 완성된 글로 보낸다.
알림으로 가는 문구는 -습니다체 (용어 통일 규칙).
실제 문장은 기획, 디자인과 확정 전까지 임시.
놓친 내용, 투표 결과는 백엔드 템플릿이라 여기 없음.
"""
from datetime import date

_WEEKDAY_KO = "월화수목금토일"

# ---------- 선택기 행동 ----------


def vote_opened(agenda_title: str, option_names: list[str]) -> str:
    """투표 열기 (현황판 카드)."""
    return f"'{agenda_title}' 투표가 열렸습니다. 선택지: {', '.join(option_names)}"


def participation_nudge(member_name: str, agenda_title: str, timing: str) -> str:
    """참여 알림 (의견 없는 팀원, 알림 / PC 알림). timing: 'half' | '1h'.

    버튼(선택지, 상관없음, 익명으로 의견 남기기)은 프론트가 그림.
    안 읽은 팀원에게는 백엔드가 놓친 내용 문구를 아래에 붙임.
    """
    when = "마감까지 1시간 남았습니다." if timing == "1h" else "마감까지 절반 남았습니다."
    return f"{member_name}님, '{agenda_title}'에 아직 의견이 없습니다. {when} 선택지를 고르기만 해도 됩니다."


CONCLUSION_SUGGEST = "결론 초안을 만들까요?"  # 결론 초안 제안 카드 + [생성]

# ---------- 호출 안내 (선택기가 '대기'와 함께 돌려줌, 부른 사람에게만) ----------
VOTE_ALREADY_OPEN = "이미 투표가 열려 있습니다."
NO_OPTIONS_YET = "아직 선택지가 없습니다."
NO_ACTIVE_AGENDA = "진행 중인 안건이 없습니다."
CONCLUSION_IN_PROGRESS = "지금은 결론 초안을 확정하는 중입니다."
DEADLINE_PASSED = "의견 마감이 지났습니다. '@Pubble 결론 내줘'로 결론 초안을 요청할 수 있습니다."

# ---------- 결론 초안 상태 ----------
NO_CONCLUSION = "아직 합의된 결론이 없습니다. 의견이 더 모이면 다시 요청할 수 있습니다."
GENERATION_FAILED = "결론 초안을 만들지 못했습니다. [다시 생성]을 눌러 주세요."

# ---------- 익명 체크 안내 ----------
PRIVATE_NOTICE = "이 메시지는 채팅에 표시되지 않습니다. 결론에 반영되면 회의록에 이름 없이 근거로 표시될 수 있습니다."

# ---------- 할 일 ----------


def fmt_due(d: date | None) -> str:
    return f"{d.month}/{d.day}({_WEEKDAY_KO[d.weekday()]})" if d else "마감 없음"


def todo_request(owner_name: str, task: str, due: date | None) -> str:
    """할 일 캐치, 결론 초안의 새 할 일 → 담당자에게 [승인] 요청."""
    return f"{owner_name}님에게 할 일 요청이 있습니다. {task} (마감 {fmt_due(due)})"
