# Pubble AI 서버

FastAPI 서버 하나. 아무것도 저장하지 않고, 백엔드가 데이터를 담아 부르면 결과만 돌려줌.

- `/write/structure`, `/write/summary`, `/write/conclusion`: 구조화, 상황 요약, 결론 (가은)
- 반응 분류, 관계 판단, 현황판(`/board`), 진행 규칙: 연이 `app/routers/`에 추가하고 `app/main.py`에서 include
- 검증은 `/write/*` 안에서 내부 호출 (엔드포인트 없음)
- 기준 문서: 노션 '구조화 출력 JSON 스키마 확정' 카드, '합성 대화 데이터 생성 기준 (v2)', '[백엔드 전달] 바뀐 기능 + AI 서버 API 초안'

## 실행

```bash
pip install -r requirements.txt
cp .env.example .env           # ANTHROPIC_API_KEY 채우기 (.env는 git에 안 올라감)
set -a; source .env; set +a
uvicorn app.main:app --reload
# http://localhost:8000/docs 에서 요청/응답 형식 확인
pytest -q                      # 가짜 LLM으로 테스트 (API 키 필요 없음)
```

자체 모델로 바꿀 때 (학습 뒤):

```bash
llama-server -m qwen3-1.7b-pubble-q4.gguf --port 8080   # 4bit GGUF, CPU
export LLM_PRIMARY=local LLM_FALLBACK=api               # 실패하면 Claude로 대체
```

결론은 항상 Claude Haiku 5.5 (자체 모델로 바꾸지 않음).

## 구조

```
app/
  main.py                    서버, 라우터 연결
  config.py                  LLM 고르기 (api = Claude / local = Qwen3 + Claude 대체), 현황판 설정
  schemas/common.py          공통 형식 (팀원, 메시지 + user_reply_to, 근거 문장, 할 일, 상태)
  schemas/write.py           구조화, 상황 요약, 결론 요청/응답
  schemas/board.py           현황판 요청/응답 (연)
  routers/write.py           POST /write/{structure, summary, conclusion}
  llm/anthropic_client.py    Claude Haiku 5.5 (effort, system 프롬프트 캐싱)
  llm/openai_compat.py       llama-server(Qwen3, non-thinking), OpenAI 호환 모델
  services/prompts.py        task별 user 프롬프트 (선생 LLM, 자체 모델, 학습 데이터가 같은 형식)
  services/teacher_guides.py 선생 LLM에만 붙이는 작성 기준 + 예시 (v2 기준)
  services/writer.py         LLM → JSON → 형식 확인 → 검증 → 재시도 → 대체
  services/verifier.py       검증기 연결 지점: verify(task, 문장, 근거[ID, 이름, 내용]) → passed, score, reason (연 NLI로 교체)
  services/dates.py          상대 날짜 → 마감 ("담주까지" = 다음 주 일요일)
  services/board.py          현황판 5칸 계산 규칙 (연)
pipeline/                    가상 대화 데이터: 주문서(orders) → Gemini 생성(generate) → Claude 라벨(label) → 비용(cost)
tests/                       가짜 LLM 테스트
scripts/try_teacher.py       예시 대화로 Claude 3개 task 돌려보기 (effort 비교)
scripts/make_dialogs.py      대화 N개 생성 + 라벨 + 비용 계산
```

## 처리 흐름 (writer.py)

1. task별 프롬프트로 LLM 호출 (JSON만 출력)
2. 형식 확인: 정해진 값(type, stance) 밖이면 다시 쓰기, 입력에 없는 ID는 버림, 근거가 없는 포인트나 문장은 버림
3. 검증: 남은 포인트, 문장마다 검증기 호출. 근거 없음, 검증기 오류, 시간 초과(VERIFY_TIMEOUT)는 탈락
4. 쓸 수 없으면 같은 모델로 한 번 더 → 대체 모델(Claude) 한 번 → 그래도 안 되면 `status: failed`
5. 쓴 결과가 검증에서 전부 탈락하면 `status: skipped`

## task별 규칙

| task | 코드에서 하는 것 | status |
| --- | --- | --- |
| structure | 포인트 ID는 코드가 붙임(`msg_N-순번`). `answer_to`는 `open_items`에 있는 ID만. 맡은 사람이 없는 할 일 → 요청. 마감은 dates.py 규칙 우선. 할 일이 아니면 owner, due 비움 | ok (포인트 없음 포함) / skipped / failed |
| summary | 근거는 현황판 항목 ID. 검증은 항목 내용(문장, 사람, 반대편, 담당)으로 | ok / skipped / failed (백엔드는 이전 요약 유지) |
| conclusion | 담당자 없는 할 일 → 미결 사항. 이미 할당된 할 일은 `existing_todo_id`. 마감은 dates.py 규칙 우선. 익명은 '익명'으로 (이름 추측 금지) | ok / no_conclusion (결론 없음) / failed (생성 실패) |

## 응답 공통 필드

- `status`: ok / no_conclusion / skipped / failed
- `source`: local (자체 모델) / api (Claude) / none
- `attempts`: LLM 호출 횟수 (Langfuse 붙이기 전 임시 기록용)

## 선생 LLM 프롬프트

- user 프롬프트(`prompts.py`)는 선생, 자체 모델이 똑같다 = 학습 데이터의 입력 형식
- 선생(Claude)에게만 system에 작성 기준과 예시(`teacher_guides.py`)를 더 붙인다 (캐싱)
  - 공통: 직접 나온 근거만 / 익명 작성자 짐작 금지 / 남의 의견 정리는 포인트로 안 만듦
  - task별: v2 '정답 붙이는 규칙', '헷갈릴 때 기준' + 예시 (MVP 범위 대화)
- 학습 데이터 = (user 프롬프트 → 선생 답안). 기준과 예시는 학습 입력에 안 넣음 → 자체 모델이 짧은 프롬프트만으로 선생처럼 쓰게 증류
- 구조화 모델 출력에는 `due_text`(마감 원문 표현)가 더 있음. 응답에서는 dates.py로 날짜로 바꾸고 빼냄
- 실제 호출 확인: `python -m scripts.try_teacher` (CLAUDE_EFFORT를 low / medium으로 바꿔가며 비교)

## 가상 대화 데이터 (pipeline/)

```bash
set -a; source .env; set +a                       # ANTHROPIC_API_KEY, GEMINI_API_KEY
python -m scripts.make_dialogs --n 10 --out data/raw/test10          # effort 기본값 medium
python -m scripts.compare_effort data/raw/test10_low data/raw/test10  # effort 비교할 때만 (low를 --reuse로 따로 돌린 뒤)
```

1. 주문서 (`orders.py`): v2 비율대로 안건 형태, 인원 4~8명, 메시지 50~100개, 넣을 상황 2~4개, 결말을 정함 (seed 고정)
2. 생성 (`generate.py`, Gemini): 대화 + 반응 분류 라벨(reaction, reply_to, user_reply_to) + 의도한 포인트, 단계, outcome. 형식 검사
3. 라벨 (`label.py`, Claude): 내용 있음 메시지마다 구조화 (서버와 같은 프롬프트, open_items는 앞 라벨로 계산) → 묶음 → 25/50/75/100% 시점 현황판(코드 계산)으로 상황 요약
4. 비용 (`cost.py`): 단계별 토큰과 비용, 300개 예상 (일반 / Batch)
- `--reuse`: 같은 대화로 라벨만 다시 (effort 비교할 때 생성 비용 안 듦)
- 결과는 `data/raw/` (git에 안 올라감)
