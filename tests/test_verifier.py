"""검증기 연결 (연 리뷰 반영): task, 근거(ID, 이름, 내용) 전달 / 점수 / 오류는 실패."""
import asyncio

from app.schemas.write import BoardSummaryRequest, TodoCatchRequest
from app.services.verifier import Evidence, PassThroughVerifier, VerifyResult
from app.services.writer import Writer
from tests.conftest import MEMBERS, OPTIONS, SCOPE, FakeLLM, msg


class RecordingVerifier:
    """받은 값을 기록하고 정해진 결과를 돌려주는 가짜 검증기."""

    def __init__(self, result=None, error=None, delay=0.0):
        self.calls = []
        self.result = result or VerifyResult(passed=True, score=0.9)
        self.error, self.delay = error, delay

    async def verify(self, task, sentence, evidence):
        self.calls.append((task, sentence, evidence))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.result


def board_req():
    return BoardSummaryRequest(
        **SCOPE, agenda_title="장소", options=OPTIONS, members=MEMBERS, counts=[],
        messages=[msg("m1", "u1", "신촌이 교통이 나아요"), msg("m2", "u2", "홍대가 가게 많아요")],
    )


def board_llm():
    llm = FakeLLM()
    llm.queue("board_summary", *[{"issues": [{"text": "교통 vs 가게 수", "evidence": ["m1", "m2"]}],
                                  "agreements": []}] * 2)
    return llm


async def test_passthrough_fails_without_evidence():
    r = await PassThroughVerifier().verify("board_summary", "x", [])
    assert not r.passed and r.reason == "근거 없음"


async def test_verifier_gets_task_speaker_and_score():
    v = RecordingVerifier()
    r = await Writer(board_llm(), verifier=v).board_summary(board_req())
    task, sentence, evidence = v.calls[0]
    assert task == "board_summary" and sentence == "교통 vs 가게 수"
    assert evidence[0] == Evidence(message_id="m1", speaker="해원", text="신촌이 교통이 나아요")
    assert r.issues[0].verify_score == 0.9


async def test_verifier_error_is_failure():
    v = RecordingVerifier(error=RuntimeError("모델 로드 실패"))
    r = await Writer(board_llm(), verifier=v).board_summary(board_req())
    assert r.status == "failed"  # 통과시키지 않음 → 재시도 후 실패


async def test_verifier_timeout_is_failure():
    v = RecordingVerifier(delay=0.2)
    r = await Writer(board_llm(), verifier=v, verify_timeout=0.05).board_summary(board_req())
    assert r.status == "failed"


async def test_todo_sentence_has_owner_and_due():
    llm = FakeLLM()
    llm.queue("todo_catch", {"task": "견적 받기", "owner_id": "u1", "due_text": "담주까지", "due": None,
                             "evidence": ["m7"]})
    v = RecordingVerifier()
    req = TodoCatchRequest(**SCOPE, message=msg("m7", "u1", "제가 담주까지 견적 받아올게요"), members=MEMBERS)
    r = await Writer(llm, verifier=v).todo_catch(req)
    assert v.calls[0][0] == "todo_catch"
    assert v.calls[0][1] == "해원 담당: 견적 받기 (마감: 담주까지)"  # 담당자, 마감도 검증
    assert r.todo.verify_score == 0.9


async def test_anonymous_speaker_hidden():
    llm = FakeLLM()
    llm.queue("todo_catch", {"task": "예약", "owner_id": "u1", "due_text": None, "due": None,
                             "evidence": ["m6", "m7"]})
    v = RecordingVerifier()
    req = TodoCatchRequest(**SCOPE, message=msg("m7", "u1", "예약은 제가 할게요"),
                           previous_message=msg("m6", "u2", "예약 누가 해요?", anonymous=True), members=MEMBERS)
    await Writer(llm, verifier=v).todo_catch(req)
    assert v.calls[0][2][0].speaker == "익명"
