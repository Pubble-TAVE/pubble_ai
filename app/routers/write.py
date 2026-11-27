"""글 쓰기 엔드포인트 (가은 담당): 구조화, 상황 요약, 결론."""
from fastapi import APIRouter, Request

from app.schemas.write import (
    ConclusionRequest,
    ConclusionResponse,
    StructureRequest,
    StructureResponse,
    SummaryRequest,
    SummaryResponse,
)
from app.services.writer import Writer

router = APIRouter(prefix="/write", tags=["글 쓰기"])


def _writer(request: Request) -> Writer:
    return request.app.state.writer


@router.post("/structure", response_model=StructureResponse, summary="구조화: 메시지 → 포인트")
async def structure(body: StructureRequest, request: Request):
    return await _writer(request).structure(body)


@router.post("/summary", response_model=SummaryResponse, summary="상황 요약: 현황판 → 2~3문장")
async def summary(body: SummaryRequest, request: Request):
    return await _writer(request).summary(body)


@router.post("/conclusion", response_model=ConclusionResponse, summary="결론 초안 (+ 할 일, 미결 사항, 논의 흐름)")
async def conclusion(body: ConclusionRequest, request: Request):
    return await _writer(request).conclusion(body)
