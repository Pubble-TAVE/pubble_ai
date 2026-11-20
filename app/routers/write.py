"""글 쓰기 엔드포인트 (가은 담당). 경로 이름은 임시, 백엔드와 맞추면 바꿈."""
from fastapi import APIRouter, Request

from app.schemas.write import (
    BoardSummaryRequest,
    BoardSummaryResponse,
    ConclusionRequest,
    ConclusionResponse,
    NextAgendaRequest,
    NextAgendaResponse,
    OptionNormalizeRequest,
    OptionNormalizeResponse,
    TodoCatchRequest,
    TodoCatchResponse,
)
from app.services.writer import Writer

router = APIRouter(prefix="/write", tags=["글 쓰기"])


def _writer(request: Request) -> Writer:
    return request.app.state.writer


@router.post("/board-summary", response_model=BoardSummaryResponse, summary="현황판 쟁점, 합의")
async def board_summary(body: BoardSummaryRequest, request: Request):
    return await _writer(request).board_summary(body)


@router.post("/conclusion", response_model=ConclusionResponse, summary="결론 초안 (+ 할 일, 미결 사항, 논의 흐름)")
async def conclusion(body: ConclusionRequest, request: Request):
    return await _writer(request).conclusion(body)


@router.post("/option-normalize", response_model=OptionNormalizeResponse, summary="선택지 정리")
async def option_normalize(body: OptionNormalizeRequest, request: Request):
    return await _writer(request).option_normalize(body)


@router.post("/todo-catch", response_model=TodoCatchResponse, summary="할 일 캐치")
async def todo_catch(body: TodoCatchRequest, request: Request):
    return await _writer(request).todo_catch(body)


@router.post("/next-agenda", response_model=NextAgendaResponse, summary="추천 다음 안건")
async def next_agenda(body: NextAgendaRequest, request: Request):
    return await _writer(request).next_agenda(body)
