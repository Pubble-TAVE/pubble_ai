import json

from app.schemas.common import Source
from app.schemas.write import StructureRequest
from app.services import teacher_guides
from app.services.writer import Writer
from tests.conftest import MEMBERS, SCOPE, FakeLLM, msg


def _examples(guide: str):
    """'출력:' 뒤 JSON을 전부 꺼낸다."""
    dec, out, i = json.JSONDecoder(), [], 0
    while (i := guide.find("출력:", i)) != -1:
        obj, end = dec.raw_decode(guide[i + 3:].lstrip())
        out.append(obj)
        i += 3
    return out


def test_every_guide_has_valid_examples():
    assert set(teacher_guides.GUIDES) == {"structure", "summary", "conclusion"}
    for task, guide in teacher_guides.GUIDES.items():
        examples = _examples(guide)
        assert examples, task
        for ex in examples:
            assert isinstance(ex, dict), task


def test_structure_examples_follow_schema():
    for ex in _examples(teacher_guides.STRUCTURE):
        for pt in ex["points"]:
            assert pt["type"] in {"제안", "의견", "질문", "요청", "정보", "할 일"}
            assert pt["stance"] in {"찬성", "반대", "조건부", "없음"}
            assert not (pt["target"] or "").startswith("msg_")  # target에 포인트 ID를 쓰지 않음


async def test_guide_only_for_teacher():
    req = StructureRequest(**SCOPE, agenda_title="범위", members=MEMBERS,
                           message=msg("msg_1", "u1", "범위 줄이죠"), now="2026-11-24")
    local, api = FakeLLM(Source.local), FakeLLM(Source.api)
    local.queue("structure", "깨짐", "깨짐")
    api.queue("structure", {"points": []})
    await Writer(local, api, max_retries=1).structure(req)
    assert "[structure 작성 기준]" not in local.systems[0]  # 자체 모델은 짧은 프롬프트만
    assert "[structure 작성 기준]" in api.systems[0]  # 선생은 기준 + 예시
    assert local.calls[0] == api.calls[0]  # user 프롬프트는 같음 (학습 입력과 같은 형식)
