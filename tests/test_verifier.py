"""검증기 연결: task, 근거(ID, 이름, 내용) 전달 / 점수 / 오류는 실패 / 전부 걸러지면 skipped."""
import asyncio

from app.schemas.write import StructureRequest, SummaryRequest
from app.services.verifier import Evidence, PassThroughVerifier, VerifyResult
from app.services.writer import Writer
from tests.conftest import BOARD, MEMBERS, SCOPE, FakeLLM, msg


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


def structure_req(message=None, recent=()):
    return StructureRequest(
        **SCOPE, agenda_title="MVP 범위", members=MEMBERS,
        message=message or msg("msg_4", "u2", "일정이 빠듯한 건 동의합니다"), recent_messages=list(recent),
        now="2026-11-24",
    )


def point(text="12/11 일정이 빠듯함", **kw):
    return {"text": text, "type": "의견", "stance": "찬성", "reason": None, "target": "일정", "owner": None,
            "due_text": None, "due": None, "answer_to": None, "evidence": ["msg_4"], **kw}


def structure_llm(*points):
    llm = FakeLLM()
    llm.queue("structure", *[{"points": list(points or [point()])}] * 2)
    return llm


async def test_passthrough_fails_without_evidence():
    r = await PassThroughVerifier().verify("structure", "x", [])
    assert not r.passed and r.reason == "근거 없음"


async def test_verifier_gets_task_speaker_and_score():
    v = RecordingVerifier()
    r = await Writer(structure_llm(), verifier=v).structure(structure_req())
    task, sentence, evidence = v.calls[0]
    assert task == "structure" and sentence == "12/11 일정이 빠듯함"
    assert evidence[0] == Evidence(message_id="msg_4", speaker="서연", text="일정이 빠듯한 건 동의합니다")
    assert r.points[0].verify_score == 0.9


async def test_all_dropped_is_skipped():
    v = RecordingVerifier(result=VerifyResult(passed=False, score=0.1))
    r = await Writer(structure_llm(), verifier=v).structure(structure_req())
    assert r.status == "skipped" and r.points == []


async def test_verifier_error_drops_point():
    v = RecordingVerifier(error=RuntimeError("모델 로드 실패"))
    r = await Writer(structure_llm(), verifier=v).structure(structure_req())
    assert r.status == "skipped"  # 통과시키지 않음


async def test_verifier_timeout_drops_point():
    v = RecordingVerifier(delay=0.2)
    r = await Writer(structure_llm(), verifier=v, verify_timeout=0.05).structure(structure_req())
    assert r.status == "skipped"


async def test_todo_sentence_has_owner_and_due():
    v = RecordingVerifier()
    llm = structure_llm(point("디자인 시안 1차", type="할 일", stance="없음", owner="u2", due_text="금요일까지"))
    await Writer(llm, verifier=v).structure(structure_req(msg("msg_4", "u2", "시안은 제가 금요일까지 올릴게요")))
    assert v.calls[0][1] == "서연 담당: 디자인 시안 1차 (마감: 금요일까지)"  # 담당자, 마감도 검증


async def test_anonymous_speaker_hidden():
    v = RecordingVerifier()
    llm = structure_llm(point(evidence=["msg_4"]))
    await Writer(llm, verifier=v).structure(structure_req(msg("msg_4", "u2", "일정 빠듯해요", anonymous=True)))
    assert v.calls[0][2][0].speaker == "익명"


async def test_summary_verifies_against_board_items():
    v = RecordingVerifier()
    llm = FakeLLM()
    llm.queue("summary", {"sentences": [{"text": "놓친 내용 요약을 뺄지는 의견이 갈려 있어요.", "evidence": ["c3"]}]})
    await Writer(llm, verifier=v).summary(SummaryRequest(**SCOPE, agenda_title="범위", board=BOARD))
    task, _, evidence = v.calls[0]
    assert task == "summary" and evidence[0].message_id == "c3"
    assert "반대: 서연" in evidence[0].text
