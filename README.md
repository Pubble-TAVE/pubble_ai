# Pubble AI 서버 (뼈대)

FastAPI 서버 하나. 아무것도 저장하지 않고, 백엔드가 데이터를 담아 부르면 결과만 돌려줌.

- `/write/*`: 글 쓰기 5개 (가은)
- 분석기, 선택기: 연이 `app/routers/`에 추가하고 `app/main.py`에서 include
- 엔드포인트 경로와 필드 이름은 임시. 백엔드가 정하면 `app/schemas/`만 바꾸면 됨

## 실행

```bash
pip install -r requirements.txt
cp .env.example .env           # OPENAI_API_KEY, OPENAI_MODEL 채우기 (.env는 git에 안 올라감)
set -a; source .env; set +a
uvicorn app.main:app --reload
# http://localhost:8000/docs 에서 요청/응답 형식 확인
pytest -q                      # 가짜 LLM으로 테스트 (API 키 필요 없음)
```

자체 모델로 바꿀 때 (S8 이후):

```bash
llama-server -m qwen3-1.7b-pubble-q4.gguf --port 8080   # 4bit GGUF, CPU
export LLM_PRIMARY=local LLM_FALLBACK=openai
```

## 구조

```
app/
  main.py                 서버, 라우터 연결
  config.py               LLM 고르기 (openai / local + 대체)
  schemas/common.py       공통 형식 (팀원, 선택지, 메시지, 근거 문장, 할 일, 상태)
  schemas/write.py        task 5개 요청/응답
  routers/write.py        POST /write/{board-summary, conclusion, option-normalize, todo-catch, next-agenda}
  llm/openai_compat.py    OpenAI와 llama-server를 같은 코드로 (Qwen3 non-thinking)
  services/prompts.py     task별 프롬프트 (선생 LLM, 자체 모델, 학습 데이터가 같은 형식)
  services/writer.py      LLM → JSON → 근거 ID 확인 → 검증 → 재시도 → 대체
  services/verifier.py    검증기 연결 지점 (지금은 통과만, 연의 NLI로 교체)
  services/dates.py       상대 날짜 → 마감 ("담주까지" = 다음 주 일요일)
  templates/messages.py   템플릿 문구 (투표 열기, 참여 알림, 안내 문구 등)
tests/                    가짜 LLM 테스트
```

## 처리 흐름 (writer.py)

1. task별 프롬프트로 LLM 호출 (JSON만 출력)
2. 근거 ID 확인: 입력에 없는 메시지 ID는 버림, 근거가 없는 문장은 버림
3. 검증기: board_summary, conclusion, todo_catch 문장만 (통과한 문장만 응답에)
4. 쓸 수 없으면 같은 모델로 한 번 더 → 대체 모델(OpenAI) 한 번 → 그래도 안 되면 `status: failed`

## task별 규칙

| task | 코드에서 하는 것 | status |
| --- | --- | --- |
| board_summary | 익명 메시지는 프롬프트, 근거에서 뺌 (넣을지 확인 필요) | ok / failed (백엔드는 이전 문장 유지) |
| conclusion | 익명 메시지는 '익명'으로 넣음 (이름 추측 금지). 담당자 없는 할 일 → 미결 사항. 이미 할당된 할 일은 `existing_todo_id`. 마감은 dates.py 규칙 우선 | ok / no_conclusion (결론 없음) / failed (생성 실패) |
| option_normalize | 이름이 기존 선택지와 똑같으면 그 ID로 | ok / failed |
| todo_catch | 담당자 없으면 할 일로 안 잡음. 요청 문구는 템플릿 | ok / skipped / failed |
| next_agenda | 기존 후보, 기존 안건과 겹치면 뺌. 후보마다 채팅방 ID | ok / failed |

## 응답 공통 필드

- `status`: ok / no_conclusion / skipped / failed
- `source`: local (자체 모델) / api (OpenAI) / none
- `attempts`: LLM 호출 횟수 (Langfuse 붙이기 전 임시 기록용)
