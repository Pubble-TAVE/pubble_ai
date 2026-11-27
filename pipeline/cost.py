"""토큰 사용량 → 비용. 단가는 USD / 100만 토큰 (2026-11 기준, 바뀌면 여기만 고침).

- Claude Haiku 5.5 (프롬프트 10만 토큰 이하): 입력 0.10, 출력 0.50, 캐시 읽기 0.01, 캐시 쓰기 0.125
- Gemini 3.1 Flash-Lite: 입력 0.25, 출력 1.50 / Gemini 3.5 Flash-Lite: 입력 0.30, 출력 2.50
- Batch는 두 회사 모두 절반
"""
from collections import defaultdict

from pipeline.clients import Usage

PRICES = {
    "claude-haiku-5-5": {"in": 0.10, "out": 0.50, "cache_read": 0.01, "cache_write": 0.125},
    "gemini-3.1-flash-lite": {"in": 0.25, "out": 1.50, "cache_read": 0.025, "cache_write": 0.25},
    "gemini-3.5-flash-lite": {"in": 0.30, "out": 2.50, "cache_read": 0.03, "cache_write": 0.30},
}


def cost_of(u: Usage) -> float:
    p = PRICES.get(u.model)
    if p is None:
        return 0.0
    return (u.input_tokens * p["in"] + u.output_tokens * p["out"] + u.cache_read_tokens * p["cache_read"]
            + u.cache_write_tokens * p["cache_write"]) / 1_000_000


def report(rows: list[Usage], n_dialogs: int, target: int = 300, krw_per_usd: float = 1400) -> str:
    by_step: dict[str, dict] = defaultdict(lambda: defaultdict(float))
    for u in rows:
        s = by_step[f"{u.step} ({u.model})"]
        s["calls"] += 1
        s["in"] += u.input_tokens + u.cache_read_tokens + u.cache_write_tokens
        s["out"] += u.output_tokens
        s["usd"] += cost_of(u)
    total = sum(s["usd"] for s in by_step.values())
    lines = [f"대화 {n_dialogs}개 실측", "| 단계 | 호출 | 입력 토큰 | 출력 토큰 | 비용(USD) |", "| --- | --- | --- | --- | --- |"]
    for k, s in sorted(by_step.items()):
        lines.append(f"| {k} | {int(s['calls'])} | {int(s['in']):,} | {int(s['out']):,} | {s['usd']:.4f} |")
    lines.append(f"| 합계 | | | | {total:.4f} |")
    if n_dialogs:
        per = total / n_dialogs
        lines += [
            "",
            f"대화 1개당 약 ${per:.4f}",
            f"{target}개 예상: 일반 ${per * target:.2f} (약 {per * target * krw_per_usd:,.0f}원)"
            f" / Batch ${per * target / 2:.2f} (약 {per * target / 2 * krw_per_usd:,.0f}원)",
        ]
    return "\n".join(lines)
