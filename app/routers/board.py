"""현황판 엔드포인트 (연 담당): 포인트, 묶음, 반응 → 5칸. 모델 없이 규칙(app/services/board.py)으로 계산한다."""
from fastapi import APIRouter

from app.schemas.board import BoardRequest, BoardResponse
from app.services.board import compute_board

router = APIRouter(tags=["현황판"])


@router.post("/board", response_model=BoardResponse, summary="현황판 5칸 계산 (규칙)")
def board(body: BoardRequest) -> BoardResponse:
    points, clusters, reactions = body.to_domain()
    return BoardResponse.from_domain(compute_board(points, clusters, reactions))
