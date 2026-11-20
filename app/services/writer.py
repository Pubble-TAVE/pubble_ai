"""글 쓰기 5개 task 실행.

공통 흐름:
  프롬프트 → LLM → JSON 읽기 → 근거 ID 확인 (입력에 없는 ID는 버림) → 검증기 → 결과
  쓸 수 없는 결과면 같은 모델로 한 번 더 → 그래도 안 되면 대체 모델(OpenAI) → 그래도 안 되면 failed
"""
import json
import logging
from datetime import date
from typing import Awaitable, Callable

from pydantic import ValidationError

from app.llm.base import LLMClient
from app.schemas.common import Evidenced, Source, TodoItem, WriteStatus
from app.schemas.write import (
    AgendaCandidate,
    BoardSummaryRequest,
    BoardSummaryResponse,
    ConclusionDraft,
    ConclusionRequest,
    ConclusionResponse,
    NextAgendaRequest,
    NextAgendaResponse,
    OptionNormalizeRequest,
    OptionNormalizeResponse,
    TodoCatchRequest,
    TodoCatchResponse,
)
from app.services import prompts
from app.services.dates import resolve_due
from app.services.teacher_guides import teacher_system
from app.services.verifier import PassThroughVerifier, Verifier
from app.templates import messages as tpl

log = logging.getLogger("pubble.writer")


class Unusable(Exception):
    """LLM 결과를 쓸 수 없음 → 다시 쓰기."""


def _norm(s: str) -> str:
    return "".join(s.split()).lower()


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
    ):
        self.primary = primary
        self.fallback = fallback
        self.verifier = verifier or PassThroughVerifier()
        self.max_retries = max_retries

    # ---------- 공통 ----------
    async def _run(self, task: str, prompt: str, post: Callable[[dict], Awaitable[object]]):
        """(결과, 출처, 시도 횟수). 끝까지 실패하면 결과는 None.

        선생 LLM(API)에는 task별 작성 기준과 예시를 system에 더 붙인다 (teacher_guides.py).
        """
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

    async def _clean(self, items, valid: dict[str, str], verify: bool) -> tuple[list[Evidenced], int]:
        """근거 ID 확인 + 검증. (남은 문장, 버린 개수)."""
        kept, dropped = [], 0
        for it in items or []:
            e = Evidenced.model_validate(it)
            e.evidence = [i for i in e.evidence if i in valid]
            if not e.text.strip() or not e.evidence:
                dropped += 1
                continue
            if verify:
                if not await self.verifier.verify(e.text, [valid[i] for i in e.evidence]):
                    dropped += 1
                    continue
                e.verified = True
            kept.append(e)
        return kept, dropped

    # ---------- board_summary ----------
    async def board_summary(self, req: BoardSummaryRequest) -> BoardSummaryResponse:
        msgs = [m for m in req.messages if not m.anonymous]  # 익명 메시지는 현황판 문장에 안 씀 (넣을지 확인 필요)
        valid = {m.id: m.text for m in msgs}
        prompt = prompts.board_summary(req.agenda_title, req.options, req.counts, msgs, req.members)

        async def post(d):
            issues, a = await self._clean(d.get("issues"), valid, verify=True)
            agreements, b = await self._clean(d.get("agreements"), valid, verify=True)
            if (a or b) and not (issues or agreements):
                raise Unusable("쓴 문장이 모두 근거 확인/검증 실패")
            return issues, agreements

        res, src, n = await self._run("board_summary", prompt, post)
        if res is None:
            return BoardSummaryResponse(status=WriteStatus.failed, attempts=n)  # 백엔드: 이전 문장 유지
        return BoardSummaryResponse(status=WriteStatus.ok, source=src, attempts=n, issues=res[0], agreements=res[1])

    # ---------- conclusion ----------
    async def conclusion(self, req: ConclusionRequest) -> ConclusionResponse:
        valid = {m.id: m.text for m in req.messages}
        members = {m.id for m in req.members}
        assigned = {t.id for t in req.assigned_todos}
        prev = req.previous_draft.model_dump(mode="json") if req.previous_draft else None
        prompt = prompts.conclusion(
            req.agenda_title, req.options, req.counts, req.vote_result, req.messages, req.members,
            req.base_date, req.assigned_todos, prev, req.revision_request,
        )

        async def post(d):
            decision = None
            if d.get("decision"):
                kept, _ = await self._clean([d["decision"]], valid, verify=True)
                if not kept:
                    raise Unusable("결론 문장이 근거 확인/검증 실패")
                decision = kept[0]

            todos, moved = [], []
            for t in d.get("todos") or []:
                owner = t.get("owner_id")
                if owner not in members:  # 담당자가 없으면 할 일이 아니라 미결 사항
                    moved.append({"text": t.get("task", ""), "evidence": t.get("evidence", [])})
                    continue
                kept, _ = await self._clean([{"text": t["task"], "evidence": t.get("evidence", [])}], valid, True)
                if not kept:
                    continue
                todos.append(
                    TodoItem(
                        task=t["task"],
                        owner_id=owner,
                        due=resolve_due(t.get("due_text"), req.base_date) or _parse_date(t.get("due")),
                        evidence=kept[0].evidence,
                        existing_todo_id=t.get("existing_todo_id") if t.get("existing_todo_id") in assigned else None,
                        verified=True,
                    )
                )
            open_issues, _ = await self._clean((d.get("open_issues") or []) + moved, valid, verify=True)
            flow, _ = await self._clean(d.get("flow"), valid, verify=True)
            return ConclusionDraft(decision=decision, todos=todos, open_issues=open_issues, flow=flow)

        draft, src, n = await self._run("conclusion", prompt, post)
        if draft is None:
            return ConclusionResponse(status=WriteStatus.failed, attempts=n)  # '생성 실패' → [다시 생성]
        status = WriteStatus.ok if draft.decision else WriteStatus.no_conclusion
        return ConclusionResponse(status=status, source=src, attempts=n, draft=draft)

    # ---------- option_normalize ----------
    async def option_normalize(self, req: OptionNormalizeRequest) -> OptionNormalizeResponse:
        by_id = {o.id: o for o in req.options}
        by_name = {_norm(o.name): o.id for o in req.options}
        prompt = prompts.option_normalize(req.agenda_title, req.message, req.options, [])

        async def post(d):
            name = (d.get("name") or "").strip()
            if not name:
                raise Unusable("선택지 이름 없음")
            matched = d.get("matched_option_id")
            if matched not in by_id:
                matched = by_name.get(_norm(name))  # 이름이 똑같으면 기존 선택지로
            if matched:
                name = by_id[matched].name
            return name, matched

        res, src, n = await self._run("option_normalize", prompt, post)
        if res is None:
            return OptionNormalizeResponse(status=WriteStatus.failed, attempts=n)
        return OptionNormalizeResponse(
            status=WriteStatus.ok, source=src, attempts=n, name=res[0], matched_option_id=res[1],
            evidence=[req.message.id],
        )

    # ---------- todo_catch ----------
    async def todo_catch(self, req: TodoCatchRequest) -> TodoCatchResponse:
        msgs = [m for m in (req.previous_message, req.message) if m]
        valid = {m.id: m.text for m in msgs}
        names = {m.id: m.name for m in req.members}
        base = req.message.sent_at.date()
        prompt = prompts.todo_catch(req.message, req.previous_message, req.members, base)

        async def post(d):
            owner = d.get("owner_id")
            if owner not in names:
                return None  # 담당자가 없으면 할 일로 안 잡음
            evidence = d.get("evidence") or [req.message.id]
            kept, _ = await self._clean([{"text": d["task"], "evidence": evidence}], valid, verify=True)
            if not kept:
                raise Unusable("할 일 근거 확인/검증 실패")
            return TodoItem(
                task=d["task"], owner_id=owner,
                due=resolve_due(d.get("due_text"), base) or _parse_date(d.get("due")),
                evidence=kept[0].evidence, verified=True,
            )

        todo, src, n = await self._run("todo_catch", prompt, post)
        if src is Source.none:
            return TodoCatchResponse(status=WriteStatus.failed, attempts=n)
        if todo is None:
            return TodoCatchResponse(status=WriteStatus.skipped, source=src, attempts=n)
        return TodoCatchResponse(
            status=WriteStatus.ok, source=src, attempts=n, todo=todo,
            display_text=tpl.todo_request(names[todo.owner_id], todo.task, todo.due),
        )

    # ---------- next_agenda ----------
    async def next_agenda(self, req: NextAgendaRequest) -> NextAgendaResponse:
        valid = {m.id: m.text for m in req.other_agenda_messages}
        for issue in req.open_issues:
            for i in issue.evidence:
                valid.setdefault(i, issue.text)
        taken = {_norm(x) for x in req.existing_candidates + req.existing_agendas}
        prompt = prompts.next_agenda(
            req.open_issues, req.other_agenda_messages, req.existing_candidates, req.existing_agendas, []
        )

        async def post(d):
            out = []
            for c in d.get("candidates") or []:
                title = (c.get("title") or "").strip()
                ev = [i for i in c.get("evidence", []) if i in valid]
                if not title or not ev or _norm(title) in taken:
                    continue
                taken.add(_norm(title))
                out.append(AgendaCandidate(title=title, reason=c.get("reason", ""), evidence=ev,
                                           chat_room_id=req.chat_room_id))
            return out

        res, src, n = await self._run("next_agenda", prompt, post)
        if res is None:
            return NextAgendaResponse(status=WriteStatus.failed, attempts=n)
        return NextAgendaResponse(status=WriteStatus.ok, source=src, attempts=n, candidates=res)
