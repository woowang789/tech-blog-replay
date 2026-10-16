"""3단계 3-D 실행기: 발급 API의 처리량과 Redis가 쓴 시간을 방식(ISSUE_MODE)마다 재서 비교한다.

제한 수량을 넉넉히 두고(마감 없이 모든 요청이 수량 검사를 통과) 사용자 VUS명이 쉬지 않고 요청한다(closed model).
예열 뒤 Redis의 명령 통계(INFO commandstats)를 비우고 재서, 요청 1건당 Redis가 명령에 쓴 시간을 함께 적는다.
결과는 results/throughput-<이름>/ (report.txt, k6.csv, k6-summary.txt, commandstats.txt, summary.json).

사용법: python3 scripts/throughput.py <이름> [VU 수, 기본 100] [지속 초, 기본 10]
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from scenario import COUPON, WARMUP_LIMIT, current_settings, describe_mode, fmt_ms, load_k6, percentile, reset, wait_drained, wait_ready, warm_up

# 수량 관리에 쓰이는 명령. 이 밖의 명령(CLIENT, INFO 등)은 실험 도구가 보낸 것이다
COUNT_COMMANDS = ["get", "incr", "decr", "evalsha", "eval", "set", "expireat", "pexpireat"]


def redis(*args):
    result = subprocess.run(["docker", "compose", "exec", "-T", "redis", "redis-cli", *args], capture_output=True, text=True)
    return result.stdout


def command_stats():
    # {명령: (횟수, 실행 시간 합 µs)}
    stats = {}
    for line in redis("INFO", "commandstats").splitlines():
        if line.startswith("cmdstat_"):
            name, fields = line[len("cmdstat_"):].split(":", 1)
            values = dict(f.split("=") for f in fields.strip().split(","))
            stats[name] = (int(values["calls"]), int(values["usec"]))
    return stats


def run_k6(out_dir, vus, duration):
    env = dict(os.environ, VUS=str(vus), DURATION=f"{duration}s", COUPON=COUPON, K6_CSV_TIME_FORMAT="unix_milli")
    result = subprocess.run(["k6", "run", "--quiet", "--out", f"csv={out_dir / 'k6.csv'}", "k6/throughput.js"],
                            env=env, capture_output=True, text=True)
    (out_dir / "k6-summary.txt").write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode != 0:
        sys.exit(f"k6가 실패했다. {out_dir / 'k6-summary.txt'}를 본다")


def main(name, vus, duration):
    os.chdir(Path(__file__).resolve().parent.parent)
    wait_ready()
    settings = current_settings()
    out_dir = Path("results") / f"throughput-{name}"
    out_dir.mkdir(parents=True, exist_ok=True)
    warm_up(out_dir)
    reset(WARMUP_LIMIT)
    redis("CONFIG", "RESETSTAT")

    started = time.time()
    run_k6(out_dir, vus, duration)
    summary, drained_at = wait_drained()
    stats = command_stats()

    responses, _ = load_k6(out_dir)
    if not responses:
        sys.exit("k6가 응답을 하나도 기록하지 않았다. k6-summary.txt를 본다")
    durations = [r[1] for r in responses]
    counts = {}
    for _, _, status in responses:
        counts[status] = counts.get(status, 0) + 1
    requests = len(responses)

    lines = [f"== {name} ({time.strftime('%H:%M:%S')})",
             f"설정: {describe_mode(settings)} / 워커 소비자 {settings['worker']}개 / 사용자 {vus}명이 {duration}초 동안 쉬지 않고 요청 "
             f"(제한 수량 {WARMUP_LIMIT:,}개라 마감 없음)"]
    others = {s: n for s, n in counts.items() if s != "200"}
    if others:
        lines.append(f"주의: 200이 아닌 응답이 있다: {others}")
    if summary["successResponses"] != requests:
        lines.append(f"주의: k6가 받은 응답 {requests:,}건과 앱이 센 성공 응답 {summary['successResponses']:,}건이 다르다. 다른 요청이 섞였다")
    if summary["queued"] != 0 or summary["successResponses"] != summary["issued"] + summary["unissued"]:
        lines.append("주의: 워커가 다 처리하지 못했다. 성공 응답 ≠ 발급 + 미발급")
    if summary["redisCount"] != summary["issued"]:
        lines.append(f"주의: Redis 수량({summary['redisCount']:,})과 DB 발급 수({summary['issued']:,})가 다르다")
    lines += [
        f"처리량: 요청 {requests:,}건, 초당 {requests / duration:,.0f}건. 응답 시간 중앙값 {fmt_ms(percentile(durations, 50))}, "
        f"p95 {fmt_ms(percentile(durations, 95))}, p99 {fmt_ms(percentile(durations, 99))}, 최대 {fmt_ms(max(durations))}",
        f"결과: 발급 {summary['issued']:,}건, 미발급 {summary['unissued']:,}건, 과발급 {summary['overIssued']:,}건. "
        f"워커가 다 처리한 시각 +{drained_at - started:.1f}초 (요청은 {duration}초까지)",
        "",
        "Redis 명령 (예열 뒤 통계를 비우고 셈. 앞단과 워커의 명령이 모두 들어간다)",
        "  명령         횟수   요청 1건당   실행 시간 합   1번 평균",
    ]
    # Lua 방식에서는 GET·INCR·SET·EXPIREAT가 스크립트 안에서 불린 것이고, 그 시간은 EVALSHA의 시간에 이미 들어 있다. 합계에서 뺀다
    inner = {"get", "incr", "set", "expireat"} if settings["mode"] == "lua" else set()
    total_calls = total_usec = 0
    for command in COUNT_COMMANDS:
        calls, usec = stats.get(command, (0, 0))
        if calls:
            note = "  (스크립트 안에서 불림. EVALSHA 시간에 포함)" if command in inner else ""
            if command not in inner:
                total_calls += calls
                total_usec += usec
            lines.append(f"  {command.upper():<9} {calls:9,}   {calls / requests:8.2f}번   {usec / 1000:9,.0f}ms   {usec / calls:6.1f}µs{note}")
    lines.append(f"  앱이 보낸 명령 합계: 요청 1건당 {total_calls / requests:.2f}번, {total_usec / requests:.1f}µs. "
                 f"Redis가 명령 실행에 쓴 시간 합 {total_usec / 1000:,.0f}ms / 실행 {duration}초")
    text = "\n".join(lines)
    print(text)
    (out_dir / "report.txt").write_text(text + "\n", encoding="utf-8")
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "commandstats.txt").write_text("\n".join(f"{c} calls={n} usec={u}" for c, (n, u) in sorted(stats.items())) + "\n",
                                              encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 100, int(sys.argv[3]) if len(sys.argv) > 3 else 10)
