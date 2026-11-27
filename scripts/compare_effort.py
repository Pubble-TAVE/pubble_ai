"""low/medium 라벨을 나란히 놓고 비교하는 파일(compare.md)을 만든다.

    python -m scripts.compare_effort data/raw/test10_low2 data/raw/test10_medium2

- 맨 위: 대화별 숫자 비교 (포인트 수, 탈락, 묶음 수, 결과가 다른 메시지 수)
- 아래: 결과가 다른 메시지만 원문 + low + medium 포인트, 마지막 상황 요약
"""
import json
import sys
from pathlib import Path


def fmt_points(entry: dict | None) -> str:
    if not entry:
        return "  (없음)"
    if entry["problems"]:
        return "  탈락: " + "; ".join(entry["problems"])
    if not entry["points"]:
        return "  (포인트 없음)"
    lines = []
    for p in entry["points"]:
        extra = [f"target {p.get('target')}"]
        if p.get("owner"):
            extra.append(f"owner {p['owner']}")
        if p.get("due_text"):
            extra.append(f"due {p['due_text']}")
        if p.get("answer_to"):
            extra.append(f"답 {p['answer_to']}")
        lines.append(f"  - [{p['type']}/{p.get('stance')}] {p['text']} ({', '.join(extra)})")
    return "\n".join(lines)


def key(entry: dict | None):
    if not entry or entry["problems"]:
        return None
    return [(p["type"], p.get("stance"), p.get("target"), p.get("owner"), p.get("answer_to")) for p in entry["points"]]


def summary_text(labels: dict) -> str:
    if not labels.get("summaries"):
        return "(없음)"
    raw = labels["summaries"][-1]["raw"]
    try:
        return "\n".join(f"- {s['text']}" for s in json.loads(raw)["sentences"])
    except (json.JSONDecodeError, KeyError, TypeError):
        return raw


def main(low_dir: Path, med_dir: Path):
    table = ["| 대화 | 메시지 | 포인트 low/med | 탈락 low/med | 묶음 low/med | 다른 메시지 |", "|---|---|---|---|---|---|"]
    body = []
    for lf in sorted(low_dir.glob("dlg_*.json")):
        mf = med_dir / lf.name
        if not mf.exists():
            continue
        low, med = (json.loads(f.read_text(encoding="utf-8")) for f in (lf, mf))
        ls, ms = low.get("labels", {}).get("structure", {}), med.get("labels", {}).get("structure", {})
        msgs = {m["id"]: m for m in low["dialog"]["messages"]}
        names = {m["id"]: m["name"] for m in low["order"]["members"]}
        diff = [mid for mid in ls.keys() | ms.keys() if key(ls.get(mid)) != key(ms.get(mid))]
        diff.sort(key=lambda x: int(x.split("_")[1]))

        def count(s):
            return sum(len(e["points"]) for e in s.values()), sum(1 for e in s.values() if e["problems"])

        (lp, lb), (mp, mb) = count(ls), count(ms)
        lc = len(low.get("labels", {}).get("clusters", {}).get("clusters", []))
        mc = len(med.get("labels", {}).get("clusters", {}).get("clusters", []))
        table.append(f"| {lf.stem} | {len(msgs)} | {lp}/{mp} | {lb}/{mb} | {lc}/{mc} | {len(diff)} |")

        body.append(f"\n## {lf.stem} — {low['order']['agenda']} ({low['order']['form']})\n")
        for mid in diff:
            m = msgs[mid]
            body.append(f"**{mid} {names.get(m['speaker'], m['speaker'])}**: {m['text']}\n")
            body.append(f"- low\n{fmt_points(ls.get(mid))}\n- medium\n{fmt_points(ms.get(mid))}\n")
        body.append(f"### 마지막 상황 요약\nlow\n{summary_text(low.get('labels', {}))}\n\n"
                    f"medium\n{summary_text(med.get('labels', {}))}\n")

    out = med_dir / "compare.md"
    out.write_text("# low vs medium 비교\n\n" + "\n".join(table) + "\n" + "\n".join(body), encoding="utf-8")
    print("\n".join(table))
    print(f"\n자세한 비교: {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
