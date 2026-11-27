"""가상 회의 대화 생성 + 선생 라벨 + 비용 계산.

    set -a; source .env; set +a
    python -m scripts.make_dialogs --n 10 --effort low --out data/raw/test10_low
    python -m scripts.make_dialogs --n 10 --effort medium --out data/raw/test10_medium --reuse data/raw/test10_low

- --reuse: 이미 생성한 대화를 다시 써서 라벨(effort)만 비교 (생성 비용 안 듦)
- 결과: 대화마다 {id}.json (주문서, 대화, 형식 검사, 라벨), usage.jsonl, cost.md
- 지금은 일반 API로 호출 (실측용). 300개는 Batch로 돌려야 절반 가격
"""
import argparse
import asyncio
import json
import os
from dataclasses import asdict
from pathlib import Path

from pipeline import generate
from pipeline.clients import ClaudeCaller, GeminiCaller, UsageLog
from pipeline.cost import report
from pipeline.label import label_dialog
from pipeline.orders import make_orders


async def one(order, out: Path, reuse: Path | None, gemini, claude, log: UsageLog, sem: asyncio.Semaphore):
    try:
        await _one(order, out, reuse, gemini, claude, log, sem)
    except Exception as e:  # 대화 하나가 실패해도 나머지는 계속
        print(f"{order['id']}: 실패 ({type(e).__name__}: {e})")


async def _one(order, out: Path, reuse: Path | None, gemini, claude, log: UsageLog, sem: asyncio.Semaphore):
    async with sem:
        if reuse and (reuse / f"{order['id']}.json").exists():
            saved = json.loads((reuse / f"{order['id']}.json").read_text(encoding="utf-8"))
            order, dialog = saved["order"], saved["dialog"]
        else:
            raw = await gemini.call("generate", generate.SYSTEM, generate.prompt(order), log)
            try:
                dialog = generate.parse(raw)
            except json.JSONDecodeError:
                (out / f"{order['id']}.json").write_text(json.dumps({"order": order, "raw": raw}, ensure_ascii=False),
                                                         encoding="utf-8")
                print(f"{order['id']}: 생성 JSON 깨짐")
                return
        problems = generate.check(order, dialog)
        (out / f"{order['id']}.json").write_text(json.dumps(  # 라벨 전에 대화부터 저장 (라벨이 실패해도 --reuse 가능)
            {"order": order, "dialog": dialog, "problems": problems}, ensure_ascii=False, indent=1), encoding="utf-8")
        labels = await label_dialog(order, dialog, claude, log) if dialog.get("messages") else {}
        bad = sum(1 for e in labels.get("structure", {}).values() if e["problems"])
        bad_cluster = len(labels.get("clusters", {}).get("problems", []))
        (out / f"{order['id']}.json").write_text(json.dumps(
            {"order": order, "dialog": dialog, "problems": problems, "labels": labels}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        print(f"{order['id']}: 메시지 {len(dialog.get('messages', []))}개, 생성 문제 {len(problems)}, 구조화 탈락 {bad}, 묶음 문제 {bad_cluster}")


async def main(a):
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    gemini = GeminiCaller(a.gemini_model, os.getenv("GEMINI_API_KEY"),
                          os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"))
    claude = ClaudeCaller(a.claude_model, a.effort, os.getenv("ANTHROPIC_API_KEY"))
    log = UsageLog()
    sem = asyncio.Semaphore(a.parallel)
    orders = make_orders(a.n, seed=a.seed)
    await asyncio.gather(*(one(o, out, Path(a.reuse) if a.reuse else None, gemini, claude, log, sem) for o in orders))
    with (out / "usage.jsonl").open("w", encoding="utf-8") as f:
        for u in log.rows:
            f.write(json.dumps(asdict(u), ensure_ascii=False) + "\n")
    text = f"effort: {a.effort}, 생성: {a.gemini_model}\n\n" + report(log.rows, a.n)
    (out / "cost.md").write_text(text, encoding="utf-8")
    print("\n" + text)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--effort", default=os.getenv("CLAUDE_EFFORT", "low"))
    ap.add_argument("--claude-model", default=os.getenv("CLAUDE_MODEL", "claude-haiku-5-5"))
    ap.add_argument("--gemini-model", default=os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite"))
    ap.add_argument("--out", default="data/raw/test10")
    ap.add_argument("--reuse", default=None)
    ap.add_argument("--parallel", type=int, default=3)
    asyncio.run(main(ap.parse_args()))
