"""k6 CSV 결과를 5초 단위로 묶어 '응답이 끝난 시각' 기준 성공/실패 건수와 p95를 보여 준다.

사용법: python3 scripts/k6_timeline.py results/k6.csv
"""
import csv
import sys
from collections import defaultdict

BUCKET_SECONDS = 5
BAR_WIDTH = 40


def p95(values):
    s = sorted(values)
    return s[min(len(s) - 1, round(0.95 * (len(s) - 1)))]


def main(path):
    buckets = defaultdict(lambda: {"ok": 0, "fail": 0, "durations": []})
    start = None
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            if row["metric_name"] != "http_req_duration":
                continue
            ts = int(float(row["timestamp"]))
            start = ts if start is None else min(start, ts)
            b = buckets[ts]
            b["ok" if row["status"] == "200" else "fail"] += 1
            b["durations"].append(float(row["metric_value"]))

    merged = defaultdict(lambda: {"ok": 0, "fail": 0, "durations": []})
    for ts, b in buckets.items():
        m = merged[(ts - start) // BUCKET_SECONDS * BUCKET_SECONDS]
        m["ok"] += b["ok"]
        m["fail"] += b["fail"]
        m["durations"] += b["durations"]

    peak = max(max(m["ok"], m["fail"]) for m in merged.values())
    scale = max(1, peak / BAR_WIDTH)
    print(f"{'구간(초)':>10} {'성공':>6} {'실패':>6} {'p95(ms)':>9}  성공(█) / 실패(▒)")
    for sec in range(0, max(merged) + 1, BUCKET_SECONDS):
        m = merged.get(sec, {"ok": 0, "fail": 0, "durations": []})
        p = f"{p95(m['durations']):.0f}" if m["durations"] else "-"
        bar = "█" * round(m["ok"] / scale) + "▒" * round(m["fail"] / scale)
        print(f"{sec:>4}~{sec + BUCKET_SECONDS:<5} {m['ok']:>6} {m['fail']:>6} {p:>9}  {bar}")


if __name__ == "__main__":
    main(sys.argv[1])
