import json

from app.schemas.common import Source
from app.schemas.write import OptionNormalizeRequest
from app.services import teacher_guides
from app.services.writer import Writer
from tests.conftest import OPTIONS, SCOPE, FakeLLM, msg


def _examples(guide: str):
    """'출력:' 뒤 JSON을 전부 꺼낸다."""
    dec, out, i = json.JSONDecoder(), [], 0
    while (i := guide.find("출력:", i)) != -1:
        obj, end = dec.raw_decode(guide[i + 3:].lstrip())
        out.append(obj)
        i += 3
    return out


def test_every_guide_has_valid_examples():
    for task, guide in teacher_guides.GUIDES.items():
        examples = _examples(guide)
        assert examples, task
        for ex in examples:
            assert isinstance(ex, dict), task


async def test_guide_only_for_teacher():
    req = OptionNormalizeRequest(**SCOPE, agenda_title="장소", message=msg("m1", "u1", "건대 어때요"), options=OPTIONS)
    local, api = FakeLLM(Source.local), FakeLLM(Source.api)
    local.queue("option_normalize", "깨짐", "깨짐")
    api.queue("option_normalize", {"name": "건대", "matched_option_id": None})
    await Writer(local, api, max_retries=1).option_normalize(req)
    assert "[option_normalize 작성 기준]" not in local.systems[0]  # 자체 모델은 짧은 프롬프트만
    assert "[option_normalize 작성 기준]" in api.systems[0]  # 선생은 기준 + 예시
    assert local.calls[0] == api.calls[0]  # user 프롬프트는 같음 (학습 입력과 같은 형식)
