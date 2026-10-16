"""2단계 실행기: 1단계와 같은 조건으로 돌리면서, 요청마다 남긴 기록으로 원문이 든 세 원인을 하나씩 가른다.

기록(앱이 DB에 남긴다): 1차 검증 시각과 그때 본 수량(앞단), 2차 검증 시각과 그때 본 수량(워커), INCR이 돌려준 값.
리포트는 1단계 리포트 뒤에 원인별 증거를 붙인다. 결과는 results/evidence-<이름>/ (report.txt, records.json 등).

사용법: python3 scripts/evidence.py <이름> [제한 수량, 기본 10000] [초당 요청 수, 기본 1000] [지속 초, 기본 20]
"""
import json
import os
import sys
from pathlib import Path

from scenario import BIN_SECONDS, COUPON, execute, fmt_ms, get_json, percentile, save


def micros_to_ms(us):
    return us / 1000


def first_sold_out_at(run):
    # k6가 처음 마감(409) 응답을 받은 시각(k6 시계, 0 = 첫 요청). 응답 시각 − 걸린 시간 = 보낸 시각
    sent = [t - ms / 1000 for t, ms, status in run["responses"] if status == "409"]
    return (min(sent) - run["t0"]) if sent else None


def evidence(records, limit, run):
    issued = [r for r in records if r["result"] == "ISSUED"]
    unissued = [r for r in records if r["result"] == "UNISSUED"]
    t0 = min(r["firstCheckAt"] for r in records)  # 앱 시계의 첫 1차 검증 = 0

    def rel(us):
        return (us - t0) / 1_000_000

    # 1차 통과 순번(0부터, 1차 검증 시각 순). 순번 − 1차 때 본 수량 = 앞서 통과했지만 그때 아직 세지 않은 요청 수
    for rank, r in enumerate(sorted(records, key=lambda x: x["firstCheckAt"])):
        r["rank"] = rank
        r["blind"] = rank - r["firstCheckCount"]
    full = next((r for r in issued if r["incrResult"] == limit), None)
    t_full = full["secondCheckAt"] if full else None

    lines = ["", f"원인별 증거 (요청마다 남긴 기록 {len(records):,}건 = 발급 {len(issued):,} + 미발급 {len(unissued):,}. "
                 "시각은 앱 시계, 0 = 첫 1차 검증)"]

    # [원인 1] Time Gap
    gap_issued = [micros_to_ms(r["secondCheckAt"] - r["firstCheckAt"]) for r in issued]
    gap_unissued = [micros_to_ms(r["secondCheckAt"] - r["firstCheckAt"]) for r in unissued]
    lines += ["", "[원인 1] Time Gap: 1차 검증(앞단)부터 2차 검증(워커)까지",
              f"  1차 → 2차 시간   발급 요청 중앙값 {fmt_ms(percentile(gap_issued, 50))} / 최대 {fmt_ms(max(gap_issued))}"
              + (f",  미발급 요청 중앙값 {fmt_ms(percentile(gap_unissued, 50))} / 최대 {fmt_ms(max(gap_unissued))}" if unissued else ""),
              f"  1차 검증이 본 수량과 실제로 앞서 통과한 요청 수의 차이(그 순간 큐와 워커에 있던 요청): "
              f"중앙값 {percentile([r['blind'] for r in records], 50):,}건, 최대 {max(r['blind'] for r in records):,}건"]
    if t_full is not None:
        lines.append(f"  발급이 제한 수량에 닿은 시각({limit:,}번째 INCR): +{rel(t_full):.2f}초")
    if unissued:
        before_full = sum(1 for r in unissued if t_full is not None and r["firstCheckAt"] < t_full)
        after_full = sum(1 for r in unissued if t_full is not None and r["secondCheckAt"] >= t_full)
        lines += [f"  미발급 {len(unissued):,}건의 기록",
                  f"    1차 검증 시각   +{rel(min(r['firstCheckAt'] for r in unissued)):.2f} ~ +{rel(max(r['firstCheckAt'] for r in unissued)):.2f}초"
                  f" (제한에 닿기 전: {before_full:,}건)",
                  f"    1차 때 본 수량  {min(r['firstCheckCount'] for r in unissued):,} ~ {max(r['firstCheckCount'] for r in unissued):,}"
                  f" (모두 제한 {limit:,} 미만: {sum(1 for r in unissued if r['firstCheckCount'] < limit):,}건)",
                  f"    1차 통과 순번   {min(r['rank'] for r in unissued) + 1:,} ~ {max(r['rank'] for r in unissued) + 1:,}번째"
                  f" (제한 수량 뒤: {sum(1 for r in unissued if r['rank'] >= limit):,}건)",
                  f"    2차 검증 시각   +{rel(min(r['secondCheckAt'] for r in unissued)):.2f} ~ +{rel(max(r['secondCheckAt'] for r in unissued)):.2f}초"
                  f" (제한에 닿은 뒤: {after_full:,}건)",
                  f"    2차 때 본 수량  {min(r['secondCheckCount'] for r in unissued):,} ~ {max(r['secondCheckCount'] for r in unissued):,}"]
    # 0.5초마다: 1차 검증이 본 수량과 실제 앞선 통과 수(평균)의 벌어짐
    lines += ["  0.5초마다 1차 검증이 본 수량과 실제 앞선 통과 요청 수 (그 칸에서 1차를 통과한 요청들의 평균)",
              "    시각(초)    본 수량   앞선 통과   못 본 요청"]
    end_rel = rel(t_full) if t_full is not None else rel(max(r["firstCheckAt"] for r in records))
    b = 0
    while b * BIN_SECONDS < end_rel + BIN_SECONDS:
        lo, hi = t0 + b * BIN_SECONDS * 1_000_000, t0 + (b + 1) * BIN_SECONDS * 1_000_000
        chunk = [r for r in records if lo <= r["firstCheckAt"] < hi]
        if chunk:
            seen = sum(r["firstCheckCount"] for r in chunk) / len(chunk)
            ahead = sum(r["rank"] for r in chunk) / len(chunk)
            lines.append(f"   {b * BIN_SECONDS:+5.1f}~{(b + 1) * BIN_SECONDS:+5.1f}  {seen:9,.0f}  {ahead:9,.0f}  {ahead - seen:9,.0f}")
        b += 1

    # [원인 2] 이중 검증
    sold_out = run["summary"]["soldOutResponses"]
    first_409 = first_sold_out_at(run)
    lines += ["", "[원인 2] 이중 검증 오버헤드: 1차 검증은 무엇을 걸렀나",
              f"  1차 통과 → 2차 통과 (발급)     {len(issued):,}건",
              f"  1차 통과 → 2차 실패 (미발급)   {len(unissued):,}건",
              f"  1차 실패 (마감 응답, 2차 없음)  {sold_out:,}건",
              "  1차가 처음 마감을 돌려준 시각   " + (f"+{first_409:.2f}초 (k6 시계)" if first_409 is not None else "없음")
              + (f",  발급이 제한에 닿은 시각 +{rel(t_full):.2f}초 (앱 시계. 두 시계는 수 ms 차이)" if t_full is not None else ""),
              f"  2차에서 떨어진 {len(unissued):,}건 중 1차가 미리 막은 것: 0건 (1차를 통과했으니 여기 있다)"]

    # [원인 3] GET/INCR 원자성
    over = sorted((r for r in issued if r["incrResult"] > limit), key=lambda r: r["incrResult"])
    by_seen = {}
    for r in issued:
        by_seen.setdefault(r["secondCheckCount"], []).append(r)
    dup_values = {v: rs for v, rs in by_seen.items() if len(rs) > 1}
    lines += ["", "[원인 3] GET/INCR 원자성 부재: 워커 여럿이 같은 수량을 읽고 각자 올림",
              f"  2차 검증에서 같은 수량을 읽은 요청 묶음 {len(dup_values):,}개 (발급 {len(issued):,}건 중 "
              f"{sum(len(rs) for rs in dup_values.values()):,}건이 다른 요청과 같은 값을 봤다)",
              f"  과발급 {len(over):,}건 (INCR 결과가 제한 {limit:,}을 넘김)"]
    for r in over:
        partners = [p for p in by_seen.get(r["secondCheckCount"], []) if p is not r]
        partner = min(partners, key=lambda p: abs(p["secondCheckAt"] - r["secondCheckAt"])) if partners else None
        detail = (f"같은 값을 읽은 요청: 사용자 {partner['userId']:,} (GET 간격 {abs(partner['secondCheckAt'] - r['secondCheckAt']):,}µs, "
                  f"INCR 결과 {partner['incrResult']:,})" if partner else "같은 값을 읽은 요청 없음")
        lines.append(f"    사용자 {r['userId']:,}: 2차 때 본 수량 {r['secondCheckCount']:,} → INCR 결과 {r['incrResult']:,}. {detail}")
    if not over:
        lines.append("    이 실행에서는 제한 수량에 닿는 순간 워커끼리 겹치지 않았다. 2-C에서 그 순간을 여러 번 만들어 본다")
    return "\n".join(lines)


def main(name, limit, rate, duration):
    os.chdir(Path(__file__).resolve().parent.parent)
    out_dir = Path("results") / f"evidence-{name}"
    run = execute(name, limit, rate, duration, out_dir)
    records = get_json(f"/experiments/records?couponId={COUPON}")
    if len(records) != run["summary"]["issued"] + run["summary"]["unissued"]:
        run["text"] += f"\n주의: 기록 {len(records):,}건이 발급 + 미발급 {run['summary']['issued'] + run['summary']['unissued']:,}건과 다르다"
    text = run["text"] + "\n" + evidence(records, limit, run)
    print(text)
    run["text"] = text
    save(out_dir, run)
    (out_dir / "records.json").write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 10000, int(sys.argv[3]) if len(sys.argv) > 3 else 1000,
         int(sys.argv[4]) if len(sys.argv) > 4 else 20)
