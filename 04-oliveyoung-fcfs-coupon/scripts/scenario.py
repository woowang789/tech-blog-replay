"""1단계 실행기: 선착순 쿠폰 발급 요청을 초당 일정 속도로 보내면서, 앞단의 응답과 워커의 발급이 시간에 따라 어떻게 벌어지는지 본다.

모든 상태를 비우고 쿠폰을 만든다 → 0.1초마다 진행 상태(성공 응답·마감 응답·발급 누계·큐 잔량)를 읽는 수집기를 띄운다
→ k6로 요청을 보낸다 → 워커가 큐를 다 비울 때까지 기다린다 → 집계(summary)를 받아 리포트를 만든다.
결과는 results/scenario-<이름>/에 남는다 (report.txt, k6.csv, k6-summary.txt, progress.csv, summary.json).

사용법: python3 scripts/scenario.py <이름> [제한 수량, 기본 10000] [초당 요청 수, 기본 2000] [지속 초, 기본 10]
"""
import csv
import json
import math
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

COUPON = "C001"
BASE_URL = "http://localhost:8080"
HEALTH_URL = "http://localhost:8081/actuator/health"
PROBE_INTERVAL = 0.1
BIN_SECONDS = 0.5
DRAIN_TIMEOUT_SECONDS = 180
# 예열: 막 뜬 앱은 JIT·커넥션·채널이 식어 있어 처음 수천 건이 몇 배 느리다. 본 실행 전에 같은 경로로 요청을 흘려 데운다
WARMUP_RATE = 1000
WARMUP_SECONDS = 8
WARMUP_LIMIT = 10_000_000


def request(url, method="GET", timeout=30):
    with urllib.request.urlopen(urllib.request.Request(url, method=method), timeout=timeout) as response:
        return response.read().decode()


def get_json(path):
    return json.loads(request(BASE_URL + path))


def wait_ready():
    for _ in range(90):
        try:
            if '"UP"' in request(HEALTH_URL, timeout=2):
                return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(2)
    sys.exit("앱이 3분 안에 뜨지 않았다. docker compose ps와 docker compose logs app으로 확인한다")


def current_settings():
    # 앱 컨테이너의 환경 변수에서 켜진 스위치를 읽는다
    env = subprocess.run(["docker", "compose", "exec", "-T", "app", "env"], capture_output=True, text=True)
    if env.returncode != 0:
        sys.exit("앱 컨테이너의 설정을 읽지 못했다. docker compose ps로 app이 떠 있는지 확인한다")
    values = dict(line.split("=", 1) for line in env.stdout.splitlines() if "=" in line)
    return {"worker": int(values.get("REPLAY_WORKERCONCURRENCY", "8"))}


def fmt_ms(ms):
    if ms >= 1000:
        return f"{ms / 1000:.2f}초"
    return f"{ms:.0f}ms" if ms >= 10 else f"{ms:.1f}ms"


def percentile(values, p):
    values = sorted(values)
    return values[min(len(values) - 1, math.ceil(p / 100 * len(values)) - 1)] if values else 0


class Probe(threading.Thread):
    # 0.1초마다 진행 상태를 읽어 (시각, 성공 응답, 마감 응답, 발급 누계(Redis), 워커 처리 완료, 큐에서 대기)를 모은다

    def __init__(self):
        super().__init__(daemon=True)
        self.samples = []
        self.running = True

    def run(self):
        while self.running:
            try:
                p = get_json(f"/experiments/progress?couponId={COUPON}")
                self.samples.append((time.time(), p["successResponses"], p["soldOutResponses"], p["redisCount"], p["handled"], p["queued"]))
            except (urllib.error.URLError, OSError, ValueError):
                pass
            time.sleep(PROBE_INTERVAL)


def run_k6(out_dir, rate, duration, prefix=""):
    # CSV의 시각을 밀리초로 남긴다(기본은 초 단위라 0.5초 칸을 나눌 수 없다). 예열(prefix="warmup-")은 CSV를 남기지 않는다
    env = dict(os.environ, RATE=str(rate), DURATION=f"{duration}s", COUPON=COUPON, K6_CSV_TIME_FORMAT="unix_milli")
    out = [] if prefix else ["--out", f"csv={out_dir / 'k6.csv'}"]
    result = subprocess.run(["k6", "run", "--quiet", *out, "k6/load.js"], env=env, capture_output=True, text=True)
    (out_dir / f"{prefix}k6-summary.txt").write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode != 0:
        sys.exit(f"k6가 실패했다. {out_dir / f'{prefix}k6-summary.txt'}를 본다")


def warm_up(out_dir):
    # 제한이 넉넉한 쿠폰으로 앞단 → MQ → 워커 → DB 경로 전체를 데운 뒤, 본 실행은 다시 초기화해서 시작한다
    request(f"{BASE_URL}/experiments/reset?couponId={COUPON}&limit={WARMUP_LIMIT}", method="POST")
    run_k6(out_dir, WARMUP_RATE, WARMUP_SECONDS, prefix="warmup-")
    wait_drained()


def load_k6(out_dir):
    # 응답마다 (응답 시각 epoch 초, 걸린 ms, HTTP 상태). k6의 timestamp는 밀리초 epoch이고 응답이 끝난 시각이다
    responses, dropped = [], 0
    with open(out_dir / "k6.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["metric_name"] == "http_req_duration":
                responses.append((int(row["timestamp"]) / 1000, float(row["metric_value"]), row["status"]))
            elif row["metric_name"] == "dropped_iterations":
                dropped += int(float(row["metric_value"]))
    return responses, dropped


def wait_drained():
    # 워커가 큐를 다 비우고 받은 메시지를 모두 처리할 때까지(성공 응답 = 발급 + 미발급) 기다린다
    deadline = time.time() + DRAIN_TIMEOUT_SECONDS
    while time.time() < deadline:
        s = get_json(f"/experiments/summary?couponId={COUPON}")
        if s["queued"] == 0 and s["successResponses"] == s["issued"] + s["unissued"]:
            return s, time.time()
        time.sleep(0.5)
    return get_json(f"/experiments/summary?couponId={COUPON}"), time.time()


def checks(limit, requests, settings, summary, responses, dropped, k6_counts):
    warnings = []
    if summary["issueLimit"] != limit:
        warnings.append(f"쿠폰의 제한 수량이 {summary['issueLimit']:,}개로 요청한 {limit:,}개와 다르다")
    if dropped:
        warnings.append(f"k6가 요청 {dropped:,}건을 제때 보내지 못했다(VU 부족). 초당 요청 수를 줄이거나 maxVUs를 늘린다")
    if k6_counts.get("other", 0):
        warnings.append(f"200·409가 아닌 응답이 {k6_counts['other']:,}건 있다. k6-summary.txt와 앱 로그를 본다")
    if abs(len(responses) + dropped - requests) > 1:  # k6가 마지막 칸에서 1건을 더 보낼 때가 있다
        warnings.append(f"응답이 {len(responses):,}건으로 요청 {requests:,}건과 다르다")
    if k6_counts.get("200", 0) != summary["successResponses"] or k6_counts.get("409", 0) != summary["soldOutResponses"]:
        warnings.append(f"k6가 받은 응답(200 {k6_counts.get('200', 0):,}, 409 {k6_counts.get('409', 0):,})과 앱이 센 응답"
                        f"(성공 {summary['successResponses']:,}, 마감 {summary['soldOutResponses']:,})이 다르다. 다른 요청이 섞였다")
    if summary["queued"] != 0:
        warnings.append(f"큐에 메시지 {summary['queued']:,}건이 남았다. 워커가 {DRAIN_TIMEOUT_SECONDS}초 안에 다 처리하지 못했다")
    if summary["successResponses"] != summary["issued"] + summary["unissued"]:
        warnings.append("성공 응답 수가 발급 + 미발급과 다르다. 워커가 아직 처리 중이거나 메시지가 사라졌다")
    if summary["redisCount"] != summary["issued"]:
        warnings.append(f"Redis 수량({summary['redisCount']:,})과 DB 발급 수({summary['issued']:,})가 다르다")
    return warnings


def timeline(t0, limit, responses, samples, drained_at):
    # 0.5초 칸마다 누계: 성공 응답, 마감 응답(k6 응답 시각 기준), 발급(Redis 수량),
    # 워커 미처리(성공 응답 − 워커 처리 완료. 큐에서 기다리거나 워커가 가져가 처리 중인 요청), 그중 큐에서 기다리는 수
    lines = ["시간표 (0.5초 단위, 0 = 첫 요청을 보낸 시각. 모두 누계)",
             "    시각(초)   성공 응답   마감 응답 | 발급(Redis)   워커 미처리 (그중 큐 대기)"]
    last = max(drained_at, max(r[0] for r in responses)) - t0
    bins = int(math.ceil(last / BIN_SECONDS))
    if bins > 10_000:
        sys.exit(f"시간표가 {bins:,}칸이다. k6.csv의 시각 단위(밀리초여야 한다)를 확인한다")
    success = soldout = 0
    sorted_responses = sorted(responses)
    i = 0
    full_marked = False
    for b in range(bins):
        end = t0 + (b + 1) * BIN_SECONDS
        while i < len(sorted_responses) and sorted_responses[i][0] < end:
            if sorted_responses[i][2] == "200":
                success += 1
            elif sorted_responses[i][2] == "409":
                soldout += 1
            i += 1
        probe = [s for s in samples if s[0] < end]
        redis_count, pending, queued = (probe[-1][3], probe[-1][1] - probe[-1][4], probe[-1][5]) if probe else (0, 0, 0)
        mark = ""
        if not full_marked and redis_count >= limit:
            mark = f"  ◀ 발급이 제한 수량에 닿음 (그때까지 성공 응답 {success:,}건)"
            full_marked = True
        lines.append(f"  {b * BIN_SECONDS:+5.1f}~{(b + 1) * BIN_SECONDS:+5.1f}  {success:9,}  {soldout:9,} | {redis_count:10,}  "
                     f"{pending:10,} ({queued:7,}){mark}")
    return lines


def report(name, limit, rate, duration, settings, summary, responses, dropped, k6_counts, samples, t0, drained_at):
    requests = rate * duration
    durations = [r[1] for r in responses]
    unissued, success = summary["unissued"], summary["successResponses"]
    last_response = max(r[0] for r in responses) - t0
    lines = [
        f"== {name} ({time.strftime('%H:%M:%S')})",
        f"설정: 워커 소비자 {settings['worker']}개 / 제한 수량 {limit:,}개, 요청 초당 {rate:,}건 × {duration}초 = {requests:,}건 (사용자마다 1번)",
        f"      본 실행 전에 예열로 초당 {WARMUP_RATE}건 × {WARMUP_SECONDS}초를 같은 경로로 흘리고 초기화했다",
    ]
    for w in checks(limit, requests, settings, summary, responses, dropped, k6_counts):
        lines.append(f"주의: {w}")
    lines += [
        f"요청: 응답 {len(responses):,}건 (200 발급 성공 {k6_counts.get('200', 0):,}건, 409 마감 {k6_counts.get('409', 0):,}건, "
        f"그 밖 {k6_counts.get('other', 0):,}건). 응답 시간 중앙값 {fmt_ms(percentile(durations, 50))}, "
        f"p99 {fmt_ms(percentile(durations, 99))}, 최대 {fmt_ms(max(durations))}",
        "",
        "결과 (워커가 큐를 다 비운 뒤)",
        f"  발급 성공 응답   {success:,}건",
        f"  실제 발급        {summary['issued']:,}건 (제한 {limit:,}개)",
        f"  미발급           {unissued:,}건  (제한 수량의 {unissued / limit * 100:.2f}%, 성공 응답의 "
        f"{(unissued / success * 100) if success else 0:.2f}%)   원문의 부하 테스트: 162건, 1.62%",
        f"  과발급           {summary['overIssued']:,}건",
        f"  Time Gap         최소 {fmt_ms(summary['gapMs']['minMs'])} / 평균 {fmt_ms(summary['gapMs']['avgMs'])} / 최대 {fmt_ms(summary['gapMs']['maxMs'])}",
        f"  마지막 응답 +{last_response:.1f}초, 워커가 다 처리한 시각 +{drained_at - t0:.1f}초 (0.5초 간격으로 확인)",
        "",
    ]
    lines += timeline(t0, limit, responses, samples, drained_at)
    return "\n".join(lines)


def reset(limit):
    # 앞 실행(예열 포함)이 남긴 것을 모두 치우고, 비었는지 확인한다
    request(f"{BASE_URL}/experiments/reset?couponId={COUPON}&limit={limit}", method="POST")
    before = get_json(f"/experiments/summary?couponId={COUPON}")
    if any(before[k] for k in ("successResponses", "soldOutResponses", "issued", "unissued", "redisCount", "queued")):
        sys.exit(f"초기화 뒤에도 남은 것이 있다: {before}")


def execute(name, limit, rate, duration, out_dir):
    # 한 번 돌리고 리포트 본문과 원본 자료를 돌려준다. 2단계 실행기(evidence.py)도 이 흐름을 그대로 쓴다
    wait_ready()
    settings = current_settings()
    out_dir.mkdir(parents=True, exist_ok=True)
    warm_up(out_dir)
    reset(limit)

    probe = Probe()
    probe.start()
    run_k6(out_dir, rate, duration)
    summary, drained_at = wait_drained()
    probe.running = False
    probe.join()

    responses, dropped = load_k6(out_dir)
    if not responses:
        sys.exit("k6가 응답을 하나도 기록하지 않았다. k6-summary.txt를 본다")
    t0 = min(r[0] - r[1] / 1000 for r in responses)
    k6_counts = {}
    for _, _, status in responses:
        key = status if status in ("200", "409") else "other"
        k6_counts[key] = k6_counts.get(key, 0) + 1

    text = report(name, limit, rate, duration, settings, summary, responses, dropped, k6_counts, probe.samples, t0, drained_at)
    return {"text": text, "settings": settings, "summary": summary, "responses": responses, "dropped": dropped,
            "k6_counts": k6_counts, "samples": probe.samples, "t0": t0, "drained_at": drained_at}


def save(out_dir, run):
    (out_dir / "report.txt").write_text(run["text"] + "\n", encoding="utf-8")
    (out_dir / "summary.json").write_text(json.dumps(run["summary"], ensure_ascii=False, indent=2), encoding="utf-8")
    with open(out_dir / "progress.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["time", "successResponses", "soldOutResponses", "redisCount", "handled", "queued"])
        writer.writerows(run["samples"])


def main(name, limit, rate, duration):
    os.chdir(Path(__file__).resolve().parent.parent)
    out_dir = Path("results") / f"scenario-{name}"
    run = execute(name, limit, rate, duration, out_dir)
    print(run["text"])
    save(out_dir, run)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 10000, int(sys.argv[3]) if len(sys.argv) > 3 else 2000,
         int(sys.argv[4]) if len(sys.argv) > 4 else 10)
