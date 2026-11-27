"""이미 라벨까지 끝난 대화에 결론만 돌려본다 (구조화를 다시 안 돌려서 싸다).

    python -m scripts.try_conclusion data/raw/test10_med_final

- 대화 끝 현황판 + 근거 메시지로 결론을 부른다 (서비스와 같은 입력)
- 결과: 폴더에 conclusion.md (생성할 때 의도한 결말 vs 결론 결과), conclusion_cost.md
"""
import asyncio
import json
import os
import sys
from pathlib import Path

from app.schemas.board import BoardResponse
from app.schemas.common import Member
from app.services import prompts
from app.services.teacher_guides import teacher_system
from pipeline.clients import ClaudeCaller, UsageLog
from pipeline.cost import report
from pipeline.label import _evidence_ids, to_messages


def fmt(outcome: dict | None, names: dict) -> str:
    if not outcome:
        return "(없음)"
    d = outcome.get("decision")
    lines = [f"- 결론: {d['text'] if d else '(합의 없음)'}"]
    for t in outcome.get("todos") or []:
        due = t.get("due_text") or t.get("due") or "마감 없음"
        lines.append(f"- 할 일: {t.get('task')} / {names.get(t.get('owner_id'), t.get('owner_id'))} / {due}")
    for o in outcome.get("open_issues") or []:
        lines.append(f"- 미결: {o['text']}")
    for f in outcome.get("flow") or []:
        lines.append(f"- 흐름: {f['text']}")
    return "\n".join(lines)


async def one(f: Path, claude, log, sem):
    async with sem:
        saved = json.loads(f.read_text(encoding="utf-8"))
        order, dialog, labels = saved["order"], saved["dialog"], saved.get("labels") or {}
        if not labels.get("summaries"):
            return f"## {f.stem}\n라벨 없음\n"
        members = [Member(id=m["id"], name=m["name"]) for m in order["members"]]
        names = {m.id: m.name for m in members}
        msgs = to_messages(dialog)
        board_json = labels["summaries"][-1]["board"]
        board = BoardResponse.model_validate(board_json)
        ev = _evidence_ids(board_json)
        user = prompts.conclusion(order["agenda"], members, board, [m for m in msgs if m.id in ev],
                                  msgs[-1].sent_at.date(), [])
        raw = await claude.call("conclusion", teacher_system(prompts.SYSTEM, "conclusion"), user, log)
        try:
            got = fmt(json.loads(raw), names)
        except json.JSONDecodeError:
            got = f"JSON 깨짐\n{raw}"
        return (f"## {f.stem} — {order['agenda']} ({order['form']}, 주문 결말: {order.get('ending')})\n\n"
                f"### 생성할 때 의도한 결말\n{fmt(dialog.get('outcome'), names)}\n\n### 결론 결과\n{got}\n")


async def main(d: Path):
    claude = ClaudeCaller(os.getenv("CLAUDE_MODEL", "claude-haiku-5-5"), os.getenv("CLAUDE_EFFORT", "medium"),
                          os.getenv("ANTHROPIC_API_KEY"))
    log, sem = UsageLog(), asyncio.Semaphore(3)
    files = sorted(d.glob("dlg_*.json"))
    parts = await asyncio.gather(*(one(f, claude, log, sem) for f in files))
    (d / "conclusion.md").write_text("# 결론 확인\n\n" + "\n".join(parts), encoding="utf-8")
    cost = report(log.rows, len(files))
    (d / "conclusion_cost.md").write_text(cost, encoding="utf-8")
    print(cost + f"\n\n자세한 결과: {d / 'conclusion.md'}")


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1])))
