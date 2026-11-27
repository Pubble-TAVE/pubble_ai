"""Pubble AI 서버.

AI 서버는 아무것도 저장하지 않는다. 백엔드가 필요한 데이터를 담아 부르면 결과만 돌려준다.
- /write/*   : 글 쓰기 5개 (가은)
- 분석기, 선택기 라우터는 연이 app/routers/에 추가해서 아래에 include
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
        primary, fallback = build_clients(s)
        app.state.writer = Writer(primary, fallback, max_retries=s.max_retries, verify_timeout=s.verify_timeout)
    yield


app = FastAPI(title="Pubble AI Server", version="0.1.0", lifespan=lifespan)
app.include_router(write.router)
# app.include_router(analyze.router)  # 연: 메시지 분석기
# app.include_router(decide.router)   # 연: 행동 선택기


@app.get("/health")
async def health():
    return {"status": "ok"}
