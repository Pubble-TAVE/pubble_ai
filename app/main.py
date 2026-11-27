"""Pubble AI 서버.

AI 서버는 아무것도 저장하지 않는다. 백엔드가 필요한 데이터를 담아 부르면 결과만 돌려준다.
- /write/*   : 구조화, 상황 요약, 결론 (가은)
- 반응 분류, 관계 판단, 현황판, 진행 규칙 라우터는 연이 app/routers/에 추가해서 아래에 include
- 검증은 /write/* 안에서 내부 호출 (엔드포인트 없음)
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings, build_clients
from app.routers import write
from app.services.writer import Writer


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not hasattr(app.state, "writer"):  # 테스트에서는 가짜 LLM을 미리 넣어둠
        s = Settings()
        primary, fallback, conclusion = build_clients(s)
        app.state.writer = Writer(
            primary, fallback, max_retries=s.max_retries, verify_timeout=s.verify_timeout,
            conclusion_client=conclusion,
        )
    yield


app = FastAPI(title="Pubble AI Server", version="0.2.0", lifespan=lifespan)
app.include_router(write.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
