"""2단계 2-C 실행기: 발급이 제한 수량에 닿는 순간을 여러 번 만들어, 과발급이 워커 소비자 수에 따라 어떻게 다른지 본다.

반복마다 초기화(제한 수량 N) → k6로 요청 M건을 한꺼번에 보낸다(k6/issue.js) → 워커가 다 처리할 때까지 기다린다 → 집계와 기록.
워커 소비자 수는 앱의 설정(WORKER_CONCURRENCY)을 따른다. 결과는 results/race-<이름>/ (report.txt, run-N.json).

사용법: python3 scripts/race.py <이름> [반복, 기본 10] [제한 수량, 기본 100] [요청 수, 기본 300]
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from scenario import COUPON, current_settings, get_json, reset, wait_drained, wait_ready

WARMUP_LIMIT = 10_000_000


def burst(requests):
    # 서로 다른 사용자가 같은 쿠폰을 한꺼번에 요청한다(0단계의 k6/issue.js)
    env = dict(os.environ, REQUESTS=str(requests), VUS=str(min(requests, 200)), COUPON=COUPON)
    result = subprocess.run(["k6", "run", "--quiet", "k6/issue.js"], env=env, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit("k6가 실패했다:\n" + result.stdout + result.stderr)


def analyze(records, limit):
    issued = [r for r in records if r["result"] == "ISSUED"]
    by_seen = {}
    for r in issued:
        by_seen.setdefault(r["secondCheckCount"], []).append(r)
    dup_groups = {v: rs for v, rs in by_seen.items() if len(rs) > 1}
    # 과발급 요청마다 같은 값을 읽은 요청 중 2차 GET 시각이 가장 가까운 짝을 찾는다
    over = []
    for r in sorted((r for r in issued if r["incrResult"] > limit), key=lambda r: r["incrResult"]):
        partners = [p for p in by_seen[r["secondCheckCount"]] if p is not r]
        partner = min(partners, key=lambda p: abs(p["secondCheckAt"] - r["secondCheckAt"])) if partners else None
        over.append((r, partner))
    return issued, dup_groups, over


def main(name, repeats, limit, requests):
    os.chdir(Path(__file__).resolve().parent.parent)
    wait_ready()
    settings = current_settings()
    out_dir = Path("results") / f"race-{name}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 예열 한 번(세지 않는다)
    reset(WARMUP_LIMIT)
    burst(requests)
    wait_drained()

    lines = [f"== {name} ({time.strftime('%H:%M:%S')})",
             f"설정: 워커 소비자 {settings['worker']}개 / 제한 수량 {limit:,}개, 요청 {requests:,}건을 한꺼번에 × {repeats}번 (예열 1번은 뺌)",
             "", "  실행   성공 응답   발급   미발급   과발급   같은 값을 읽은 묶음   과발급 요청이 2차 때 본 수량"]
    total_over = total_dup = 0
    runs_with_over = 0
    tightest = None
    for n in range(1, repeats + 1):
        reset(limit)
        burst(requests)
        summary, _ = wait_drained()
        records = get_json(f"/experiments/records?couponId={COUPON}")
        (out_dir / f"run-{n}.json").write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
        warning = ""
        if summary["queued"] != 0 or summary["successResponses"] != summary["issued"] + summary["unissued"]:
            warning = "  주의: 워커가 다 처리하지 못했다"
        if summary["redisCount"] != summary["issued"]:
            warning += f"  주의: Redis 수량 {summary['redisCount']:,} ≠ 발급 {summary['issued']:,}"
        issued, dup_groups, over = analyze(records, limit)
        total_over += len(over)
        total_dup += len(dup_groups)
        runs_with_over += 1 if over else 0
        seen_values = ", ".join(f"{r['secondCheckCount']:,}" for r, _ in over) or "-"
        lines.append(f"  {n:4d}   {summary['successResponses']:8,}   {summary['issued']:5,}   {summary['unissued']:6,}   "
                     f"{len(over):6,}   {len(dup_groups):17,}개   {seen_values}{warning}")
        for r, partner in over:
            if partner is None:
                continue
            gap = abs(partner["secondCheckAt"] - r["secondCheckAt"])
            if tightest is None or gap < tightest[0]:
                tightest = (gap, n, r, partner)
    lines += ["",
              f"과발급 합계 {total_over:,}건 ({repeats}번 중 {runs_with_over}번에서 생김). 같은 값을 읽은 묶음 합계 {total_dup:,}개",
              "  같은 값을 읽은 묶음: 2차 검증에서 워커 둘 이상이 같은 수량을 읽고 각자 INCR한 경우. 제한 수량 아래에서는 수량만 그만큼 더 오르고 끝나지만,",
              "  제한 수량 근처에서 생기면 그만큼 제한을 넘겨 발급한다"]
    if tightest:
        gap, n, a, b = tightest
        lines += [f"  과발급의 예(실행 {n}): 사용자 {a['userId']:,}와 {b['userId']:,}가 둘 다 {a['secondCheckCount']:,}을 읽음"
                  f" (GET 간격 {gap:,}µs) → INCR 결과 {b['incrResult']:,}, {a['incrResult']:,}"]
    text = "\n".join(lines)
    print(text)
    (out_dir / "report.txt").write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 10, int(sys.argv[3]) if len(sys.argv) > 3 else 100,
         int(sys.argv[4]) if len(sys.argv) > 4 else 300)
