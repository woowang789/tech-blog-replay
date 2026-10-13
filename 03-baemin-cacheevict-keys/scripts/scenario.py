"""1단계 실행기: 지금 떠 있는 앱 설정(캐시 쓰기 동기·비동기) 그대로, 상품 조회 부하 중에 전체 삭제를 한 번 부르고 결과를 요약한다.

앞 실행이 남긴 것을 치운다(Redis를 비우고 캐시를 N개로 다시 채운다) → 인기 상품을 한 번씩 조회해 앱을 데운다
→ k6/load.js: 조회 초당 200건 40초, 20초째에 전체 삭제 1번 → 요약한다.
k6는 처음 몇 초 동안 VU마다 새 연결을 열어 응답이 튈 수 있어서, 처음 10초는 요약에서 뺀다.
결과는 화면에 출력하고 results/scenario-<이름>/에도 남긴다.
  k6.csv           요청마다 응답 시간과 상태 (k6 CSV 출력, 시각은 밀리초)
  k6-summary.txt   k6가 끝나고 출력한 요약
  report.txt       화면에 출력한 요약

  시각               조회를 보낸 시각. 전체 삭제를 보낸 시각을 0으로 잡는다
  멈췄다가 풀린 때    100ms 넘게 걸린 조회가 하나라도 응답을 기다리던 구간을 이어 붙였다.
                    한 구간이 "그동안 조회가 멈춰 있다가 한꺼번에 풀린" 한 번이다
  끝남               그 0.1초 동안 응답이 돌아온 조회 수
  Redis가 받은 명령   k6를 도는 동안 Redis가 처리한 명령 수(INFO commandstats). 결과가 섞이지 않았는지 보는 데 쓴다

사용법: python3 scripts/scenario.py <이름> [캐시 키 수, 기본 1000000]
"""
import csv
import json
import math
import os
import subprocess
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

RATE = 200
DURATION_SECONDS = 40
EVICT_AT_SECONDS = 20
WARMUP_SECONDS = 10
HOT = 1000
SLOW_MS = 100
ZOOM_LIMIT_SECONDS = 8
BAR_WIDTH = 30


def request(url, method="GET", timeout=5):
    with urllib.request.urlopen(urllib.request.Request(url, method=method), timeout=timeout) as response:
        return response.read()


def compose_exec(service, *command):
    result = subprocess.run(["docker", "compose", "exec", "-T", service, *command], capture_output=True, text=True)
    return result.stdout.strip()


def redis(*command):
    return compose_exec("redis", "redis-cli", *command)


def command_calls():
    # "cmdstat_keys:calls=1,usec=213000,..." 줄에서 명령별 호출 수를 읽는다
    calls = {}
    for line in redis("INFO", "commandstats").splitlines():
        if line.startswith("cmdstat_"):
            command, stats = line[len("cmdstat_"):].split(":", 1)
            calls[command] = int(dict(item.split("=") for item in stats.split(","))["calls"])
    return calls


def ready():
    try:
        return json.loads(request("http://localhost:8081/actuator/health"))["status"] == "UP"
    except OSError:
        return False


def run_k6(out):
    env = dict(os.environ, K6_CSV_TIME_FORMAT="unix_milli", RATE=str(RATE), DURATION=f"{DURATION_SECONDS}s",
               EVICT_AT=f"{EVICT_AT_SECONDS}s", HOT=str(HOT))
    with open(out / "k6-summary.txt", "w") as summary:
        subprocess.run(["k6", "run", "--quiet", "--out", f"csv={out / 'k6.csv'}", "k6/load.js"],
                       env=env, stdout=summary, stderr=subprocess.STDOUT, check=True)


def load(path):
    # 요청마다 (보낸 시각, 응답이 온 시각, 걸린 시간, 상태). k6 CSV의 시각은 응답이 온 시각이다
    reads, evicts, dropped = [], [], 0
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            if row["metric_name"] == "dropped_iterations":
                dropped += int(float(row["metric_value"]))
            elif row["metric_name"] == "http_req_duration":
                end = int(row["timestamp"]) / 1000
                took = float(row["metric_value"]) / 1000
                (reads if row["scenario"] == "reads" else evicts).append((end - took, end, took, row["status"]))
    return reads, evicts, dropped


def fmt(seconds):
    return f"{seconds * 1000:.0f}ms" if seconds < 1 else f"{seconds:.2f}초"


def percentile(values, p):
    s = sorted(values)
    return s[min(len(s) - 1, round(p * (len(s) - 1)))]


def stalls(rel):
    # 느린 조회를 보낸 순서로 보며, 기다린 구간(보낸 시각~응답이 온 시각)이 앞 구간과 겹치면 하나로 잇는다
    merged = []
    for start, end, took, _ in sorted(r for r in rel if r[2] * 1000 > SLOW_MS):
        if merged and start <= merged[-1][1]:
            first, last, n, peak = merged[-1]
            merged[-1] = (first, max(last, end), n + 1, max(peak, took))
        else:
            merged.append((start, end, 1, took))
    return merged


def checks(immediate, count, keys_before, calls, evicts, dropped):
    warnings = []
    if keys_before != count:
        warnings.append(f"삭제 전 Redis 키가 {keys_before:,}개로 채운 수와 다르다. 앞 실행의 삭제가 아직 돌고 있었을 수 있다")
    if len(evicts) != 1 or evicts[0][3] != "200":
        warnings.append("전체 삭제가 한 번 성공하지 않았다")
    if calls.get("keys", 0) != 1:
        warnings.append(f"Redis가 받은 KEYS가 {calls.get('keys', 0)}번이다. 이번 실행 말고도 전체 삭제를 부른 곳이 있다")
    # 동기는 DEL 한 번으로, 비동기는 UNLINK 여러 번으로 지운다(0단계 결과). 반대면 앱이 다른 설정으로 떠 있다
    if immediate and (calls.get("del", 0) != 1 or "unlink" in calls):
        warnings.append("앱은 동기로 떠 있는데 Redis가 받은 삭제 명령이 다르다. 앱 이미지를 새로 빌드했는지 확인한다")
    if not immediate and ("unlink" not in calls or "del" in calls):
        warnings.append("앱은 비동기로 떠 있는데 Redis가 받은 삭제 명령이 다르다. 앱 이미지를 새로 빌드했는지 확인한다")
    if dropped:
        warnings.append(f"k6가 조회 {dropped}건을 제때 보내지 못했다")
    return [f"주의: {w}" for w in warnings] + (["  → 다시 돌린다"] if warnings else [])


def report(name, immediate, count, keys_before, calls, reads, evicts, dropped):
    mode = "원문처럼 동기" if immediate else "4.x 기본(비동기)"
    lines = [
        f"== {name} ({time.strftime('%H:%M:%S')})",
        f"설정: 캐시 쓰기 {mode}, 캐시 키 {count:,}개",
        f"      조회 초당 {RATE}건(인기 상품 {HOT:,}개 중 하나), 부하 {EVICT_AT_SECONDS}초째에 전체 삭제 1번",
        f"Redis가 받은 명령: KEYS {calls.get('keys', 0)}번, DEL {calls.get('del', 0)}번, UNLINK {calls.get('unlink', 0):,}번"
        f" (삭제 전 키 {keys_before:,}개)",
    ]
    lines += checks(immediate, count, keys_before, calls, evicts, dropped)
    if not evicts:
        return lines

    evict_start, _, evict_took, _ = evicts[0]
    since = WARMUP_SECONDS - EVICT_AT_SECONDS
    rel = [(start - evict_start, end - evict_start, took, status) for start, end, took, status in reads
           if start - evict_start >= since]
    failed = sum(1 for r in rel if r[3] != "200")
    base = [took for start, _, took, _ in rel if -5 <= start < 0]
    found = stalls(rel)
    lines += [
        f"전체 삭제: 보내고 {fmt(evict_took)} 만에 응답",
        f"조회: {len(rel):,}건, 실패 {failed}건 (k6가 연결을 여는 처음 {WARMUP_SECONDS}초는 뺐다)",
        f"  삭제 전 5초 동안: 중앙값 {fmt(percentile(base, 0.5))}, p99 {fmt(percentile(base, 0.99))}, 최대 {fmt(max(base))}",
        f"조회가 멈췄다가 한꺼번에 풀린 때: {len(found)}번",
    ]
    for start, end, n, peak in found:
        lines.append(f"  {start:+.2f}초 ~ {end:+.2f}초  조회 {n}건이 {SLOW_MS}ms 넘게 기다림, 최대 {fmt(peak)}")

    lines += ["", "1초 단위 (시각: 조회를 보낸 시각, 전체 삭제를 보낸 시각이 0)", "   시각(초)    보냄   중앙값      최대"]
    by_second = defaultdict(list)
    for start, _, took, _ in rel:
        by_second[math.floor(start)].append(took)
    for sec in range(min(by_second), max(by_second) + 1):
        values = by_second.get(sec, [])
        median = fmt(percentile(values, 0.5)) if values else "-"
        peak = fmt(max(values)) if values else "-"
        lines.append(f"  {f'{sec:+d}~{sec + 1:+d}':>9}  {len(values):>6}  {median:>7}  {peak:>8}")

    # 삭제 전후를 0.1초 단위로 본다. 전체 삭제 응답(빨라도 1초로 친다) 뒤 1초까지
    lines += ["", "삭제 전후 0.1초 단위 (보냄·최대 응답: 그 0.1초에 보낸 조회, 끝남: 그 0.1초에 응답이 온 조회)",
              "    시각(초)    보냄  끝남  최대 응답"]
    sent, done = defaultdict(list), defaultdict(int)
    for start, end, took, _ in rel:
        sent[math.floor(start * 10)].append(took)
        done[math.floor(end * 10)] += 1
    until = min(max(evict_took, 1) + 1, ZOOM_LIMIT_SECONDS)
    ticks = range(-3, math.ceil(until * 10))
    scale = max(max(sent.get(t, [0])) for t in ticks) / BAR_WIDTH or 1
    for tick in ticks:
        values = sent.get(tick, [])
        peak = max(values) if values else 0
        mark = ""
        if tick == 0:
            mark = "  ◀ 전체 삭제를 보냄"
        if tick == math.floor(evict_took * 10):
            mark += "  ◀ 전체 삭제 응답"
        bar = "█" * round(peak / scale)
        lines.append(f"  {f'{tick / 10:+.1f}~{(tick + 1) / 10:+.1f}':>10}  {len(values):>5} {done.get(tick, 0):>5}  {fmt(peak):>8}"
                     f"  {bar}{mark}")
    return lines


def main(name, count):
    os.chdir(Path(__file__).resolve().parent.parent)
    for i in range(90):
        if ready():
            break
        if i == 0:
            print("앱이 뜰 때까지 기다린다...")
        time.sleep(2)
    immediate = compose_exec("app", "printenv", "REPLAY_CACHEIMMEDIATEWRITES") == "true"

    # 앞 실행이 남긴 것을 치운다. 앞 실행의 비동기 삭제가 아직 돌고 있으면 새로 채운 키까지 지울 수 있어서,
    # 다 채우고 앱을 데운 뒤 키 수를 다시 센다
    print(f"Redis를 비우고 캐시를 {count:,}개로 채운다...")
    redis("FLUSHALL")
    request(f"http://localhost:8080/experiments/seed?count={count}", method="POST", timeout=600)
    print(f"인기 상품 {HOT:,}개를 한 번씩 조회해 앱을 데운다...")
    for product_id in range(1, HOT + 1):
        request(f"http://localhost:8080/products/{product_id}")
    keys_before = int(redis("DBSIZE"))
    redis("CONFIG", "RESETSTAT")

    out = Path(f"results/scenario-{name}")
    out.mkdir(parents=True, exist_ok=True)
    print(f"k6: 조회 초당 {RATE}건 {DURATION_SECONDS}초, {EVICT_AT_SECONDS}초째에 전체 삭제 1번...")
    run_k6(out)
    calls = command_calls()
    reads, evicts, dropped = load(out / "k6.csv")

    lines = report(name, immediate, count, keys_before, calls, reads, evicts, dropped)
    print("\n".join(lines))
    (out / "report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 1_000_000)
