"""글 쓰기 3개 task 실행: 구조화, 상황 요약, 결론.

공통 흐름:
  프롬프트 → LLM → JSON 읽기 → 형식 확인 (입력에 없는 ID는 버림) → 검증(내부 호출) → 결과
  쓸 수 없는 결과면 같은 모델로 한 번 더 → 그래도 안 되면 대체 모델(Claude) → 그래도 안 되면 failed
  구조화: 쓴 결과가 검증에서 전부 걸러지면 skipped, 끝까지 못 쓰면 failed
  상황 요약, 결론: 현황판이 비면 skipped (LLM 안 부름), 못 쓰거나 전부 걸러지면 현황판으로 템플릿 대체(template)
"""
import asyncio
import json
import logging
from datetime import date
from typing import Awaitable, Callable

from pydantic import ValidationError

from app.llm.base import LLMClient
from app.schemas.board import BoardResponse
from app.schemas.common import Evidenced, Member, Message, Source, TodoItem, WriteStatus
from app.schemas.write import (
    ConclusionDraft,
    ConclusionRequest,
    ConclusionResponse,
    Point,
    StructureRequest,
    StructureResponse,
    SummaryRequest,
    SummaryResponse,
)
from app.services import prompts
from app.services.dates import resolve_due
from app.services.teacher_guides import teacher_system
from app.services.verifier import Evidence, PassThroughVerifier, Verifier, VerifyResult

log = logging.getLogger("pubble.writer")

_TYPES = {"제안", "의견", "질문", "요청", "정보", "할 일"}
_STANCES = {"찬성", "반대", "조건부", "없음"}


class Unusable(Exception):
    """LLM 결과를 쓸 수 없음 → 다시 쓰기."""


def _evidence_map(messages: list[Message], members: list[Member]) -> dict[str, Evidence]:
    """메시지 ID → 근거 (ID, 보낸 사람 이름, 내용). 익명 메시지는 이름 대신 '익명'."""
    names = {m.id: m.name for m in members}
    return {
        m.id: Evidence(message_id=m.id, speaker="익명" if m.anonymous else names.get(m.member_id, "알 수 없음"),
                       text=m.text)
        for m in messages
    }


def _board_evidence(board: BoardResponse) -> dict[str, Evidence]:
    """현황판 항목 ID → 근거 (상황 요약 검증용). 내용은 항목 문장 + 사람 + 이유."""
    out: dict[str, Evidence] = {}
    for key in ("common", "split", "new", "need_check", "todos"):
        for i in getattr(board, key):
            people = ", ".join(p.name for p in i.people)
            parts = [i.text, f"({people})"]
            if i.opponents:
                parts.append(f"반대: {', '.join(p.name for p in i.opponents)}")
            if i.owner:
                parts.append(f"담당 {i.owner}" + (f", 마감 {i.due}" if i.due else ""))
            out[i.id] = Evidence(message_id=i.id, speaker=people or "알 수 없음", text=" ".join(parts))
    return out


def _todo_sentence(task: str, owner_name: str, due_text: str | None) -> str:
    """할 일 검증용 문장. 검증기가 담당자와 마감까지 확인할 수 있게."""
    return f"{owner_name} 담당: {task}" + (f" (마감: {due_text})" if due_text else "")


def _parse_date(s) -> date | None:
    try:
        return date.fromisoformat(s) if s else None
    except (TypeError, ValueError):
        return None


class Writer:
    def __init__(
        self,
        primary: LLMClient,
        fallback: LLMClient | None = None,
        verifier: Verifier | None = None,
        max_retries: int = 1,
        verify_timeout: float = 10.0,
        conclusion_client: LLMClient | None = None,
    ):
        self.primary = primary
        self.fallback = fallback
        self.conclusion_client = conclusion_client or primary  # 결론은 항상 Claude
        self.verifier = verifier or PassThroughVerifier()
        self.max_retries = max_retries
        self.verify_timeout = verify_timeout

    # ---------- 공통 ----------
    async def _run(self, task: str, prompt: str, post: Callable[[dict], Awaitable[object]], plan=None):
        """(결과, 출처, 시도 횟수). 끝까지 실패하면 결과는 None.

        선생 LLM(API)에는 task별 작성 기준과 예시를 system에 더 붙인다 (teacher_guides.py).
        """
        if plan is None:
            plan = [(self.primary, 1 + self.max_retries)]
            if self.fallback is not None:
                plan.append((self.fallback, 1))
        attempts = 0
        for client, tries in plan:
            for _ in range(tries):
                attempts += 1
                try:
                    system = (
                        teacher_system(prompts.SYSTEM, task) if client.source is Source.api else prompts.SYSTEM
                    )
                    raw = await client.complete(system, prompt)
                    return await post(json.loads(raw)), client.source, attempts
                except (json.JSONDecodeError, ValidationError, Unusable, KeyError, TypeError, AttributeError) as e:
                    log.warning("쓸 수 없는 결과 (%s, %d번째): %s", client.source, attempts, e)
                except Exception as e:  # 네트워크, 타임아웃 등
                    log.warning("LLM 호출 실패 (%s, %d번째): %s", client.source, attempts, e)
        return None, Source.none, attempts

    async def _verify(self, task: str, sentence: str, evidence: list[Evidence]) -> VerifyResult:
        """검증기 호출. 근거가 없거나 검증기 오류(예외, 시간 초과)면 통과가 아니라 실패."""
        if not evidence:
            return VerifyResult(passed=False, score=0.0, reason="근거 없음")
        try:
            return await asyncio.wait_for(self.verifier.verify(task, sentence, evidence), self.verify_timeout)
        except asyncio.TimeoutError:
            return VerifyResult(passed=False, score=0.0, reason="검증기 시간 초과")
        except Exception as e:
            return VerifyResult(passed=False, score=0.0, reason=f"검증기 오류: {e}")

    async def _clean(self, task: str, items, valid: dict[str, Evidence]) -> tuple[list[Evidenced], int]:
        """근거 ID 확인 + 검증. (남은 문장, 버린 개수).

        item에 '_verify_text'가 있으면 그 문장으로 검증한다 (할 일: 담당자, 마감 포함).
        """
        kept, dropped = [], 0
        for it in items or []:
            verify_text = it.get("_verify_text") if isinstance(it, dict) else None
            e = Evidenced.model_validate(it)
            e.evidence = [i for i in e.evidence if i in valid]
            if not e.text.strip() or not e.evidence:
                dropped += 1
                continue
            r = await self._verify(task, verify_text or e.text, [valid[i] for i in e.evidence])
            if not r.passed:
                log.info("검증 탈락 (%s, score=%.2f, %s): %s", task, r.score, r.reason, e.text)
                dropped += 1
                continue
            e.verified, e.verify_score = True, r.score
            kept.append(e)
        return kept, dropped

    # ---------- 구조화 ----------
    async def structure(self, req: StructureRequest) -> StructureResponse:
        msgs = [*req.recent_messages, req.message]
        valid = _evidence_map(msgs, req.members)
        names = {m.id: m.name for m in req.members}
        open_ids = {o.id for o in req.open_items}
        prompt = prompts.structure(
            req.agenda_title, req.agenda_form, req.members, req.message, req.recent_messages, req.open_items, req.now
        )

        async def post(d):
            raw_points = d["points"]
            if not isinstance(raw_points, list):
                raise Unusable("points가 목록이 아님")
            points, dropped = [], 0
            for p in raw_points:
                if p.get("type") not in _TYPES or p.get("stance") not in _STANCES:
                    raise Unusable(f"정해진 값 밖: {p.get('type')}, {p.get('stance')}")
                text = (p.get("text") or "").strip()
                evidence = [i for i in p.get("evidence") or [req.message.id] if i in valid]
                if not text or not evidence:
                    dropped += 1
                    continue
                kind, owner, due = p["type"], p.get("owner"), None
                if kind == "할 일":
                    if owner not in names:  # 맡은 사람이 없으면 할 일이 아니라 요청
                        kind, owner = "요청", None
                    else:
                        due = resolve_due(p.get("due_text"), req.now) or _parse_date(p.get("due"))
                else:
                    owner = None
                verify_text = _todo_sentence(text, names[owner], p.get("due_text")) if owner else text
                r = await self._verify("structure", verify_text, [valid[i] for i in evidence])
                if not r.passed:
                    log.info("검증 탈락 (structure, score=%.2f, %s): %s", r.score, r.reason, text)
                    dropped += 1
                    continue
                answer_to = p.get("answer_to")
                points.append(Point(
                    id=f"{req.message.id}-{len(points) + 1}",  # 포인트 ID는 코드가 붙임
                    text=text, type=kind, stance=p["stance"], reason=p.get("reason"), target=p.get("target"),
                    owner=owner, due=due, answer_to=answer_to if answer_to in open_ids else None,
                    evidence=evidence, verify_score=r.score,
                ))
            return points, dropped

        res, src, n = await self._run("structure", prompt, post)
        if res is None:
            return StructureResponse(status=WriteStatus.failed, attempts=n)
        points, dropped = res
        status = WriteStatus.skipped if dropped and not points else WriteStatus.ok
        return StructureResponse(status=status, source=src, attempts=n, points=points)

    # ---------- 상황 요약 ----------
    async def summary(self, req: SummaryRequest) -> SummaryResponse:
        if _board_empty(req.board):
            return SummaryResponse(status=WriteStatus.skipped)
        valid = _board_evidence(req.board)
        prompt = prompts.summary(req.agenda_title, req.board)

        async def post(d):
            return await self._clean("summary", d["sentences"], valid)

        res, src, n = await self._run("summary", prompt, post)
        sentences = res[0] if res else []
        if not sentences:  # 못 썼거나 전부 걸러짐 → 템플릿
            return SummaryResponse(status=WriteStatus.template, attempts=n, sentences=summary_template(req.board))
        return SummaryResponse(status=WriteStatus.ok, source=src, attempts=n, sentences=sentences)

    # ---------- 결론 ----------
    async def conclusion(self, req: ConclusionRequest) -> ConclusionResponse:
        if _board_empty(req.board):
            return ConclusionResponse(status=WriteStatus.skipped)
        valid = _evidence_map(req.evidence_messages, req.members)
        names = {m.id: m.name for m in req.members}
        existing = {t.id for t in req.existing_todos}
        prompt = prompts.conclusion(
            req.agenda_title, req.members, req.board, req.evidence_messages, req.base_date, req.existing_todos
        )

        async def post(d):
            decision = None
            if d.get("decision"):
                kept, _ = await self._clean("conclusion", [d["decision"]], valid)
                decision = kept[0] if kept else None  # 근거가 안 맞으면 결론 없음으로

            todos, moved = [], []
            for t in d.get("todos") or []:
                owner = t.get("owner_id")
                if owner not in names:  # 담당자가 없으면 할 일이 아니라 미결 사항
                    moved.append({"text": t.get("task", ""), "evidence": t.get("evidence", [])})
                    continue
                item = {"text": t["task"], "evidence": t.get("evidence", []),
                        "_verify_text": _todo_sentence(t["task"], names[owner], t.get("due_text"))}
                kept, _ = await self._clean("conclusion", [item], valid)
                if not kept:
                    continue
                todos.append(TodoItem(
                    task=t["task"], owner_id=owner,
                    due=resolve_due(t.get("due_text"), req.base_date) or _parse_date(t.get("due")),
                    evidence=kept[0].evidence,
                    existing_todo_id=t.get("existing_todo_id") if t.get("existing_todo_id") in existing else None,
                    verified=True, verify_score=kept[0].verify_score,
                ))
            open_issues, _ = await self._clean("conclusion", (d.get("open_issues") or []) + moved, valid)
            flow, _ = await self._clean("conclusion", d.get("flow"), valid)
            return ConclusionDraft(decision=decision, todos=todos, open_issues=open_issues, flow=flow)

        draft, src, n = await self._run("conclusion", prompt, post,
                                        plan=[(self.conclusion_client, 1 + self.max_retries)])
        if draft is None or not (draft.decision or draft.todos or draft.open_issues or draft.flow):
            return ConclusionResponse(status=WriteStatus.template, attempts=n,
                                      draft=conclusion_template(req.board, req.members))
        return ConclusionResponse(status=WriteStatus.ok, source=src, attempts=n, draft=draft)


# ---------- 템플릿 대체 (LLM이 못 썼을 때 현황판 그대로) ----------
def _board_empty(board: BoardResponse) -> bool:
    return not any(getattr(board, k) for k in ("common", "split", "new", "need_check", "todos"))


def summary_template(board: BoardResponse) -> list[Evidenced]:
    """칸별 첫 항목으로 최대 3문장. 근거는 현황판 항목 ID."""
    lines = [("common", "의견이 모인 것"), ("split", "의견이 갈린 것"), ("need_check", "답을 기다리는 것"),
             ("new", "새로 나온 의견"), ("todos", "맡은 일")]
    out = []
    for key, label in lines:
        items = getattr(board, key)
        if items:
            extra = f" 외 {len(items) - 1}개" if len(items) > 1 else ""
            out.append(Evidenced(text=f"{label}: {items[0].text}{extra}", evidence=[items[0].id]))
        if len(out) == 3:
            break
    return out


def conclusion_template(board: BoardResponse, members: list[Member]) -> ConclusionDraft:
    """결정은 비우고, 현황판 할 일 → 할 일, 갈림·확인 필요·새로움 → 미결 사항. 근거는 원문 메시지 ID."""
    ids = {m.name: m.id for m in members}
    todos = [TodoItem(task=i.text, owner_id=ids[i.owner], due=_parse_date(i.due), evidence=i.evidence)
             for i in board.todos if i.owner in ids]
    open_issues = [Evidenced(text=i.text, evidence=i.evidence) for k in ("split", "need_check", "new")
                   for i in getattr(board, k)]
    return ConclusionDraft(decision=None, todos=todos, open_issues=open_issues, flow=[])
