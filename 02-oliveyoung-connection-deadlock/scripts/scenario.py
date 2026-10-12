"""3단계 실행기: 지금 떠 있는 앱 설정 그대로 같은 장애 조건(메시지 30건)을 돌리고 결과를 요약한다.

앱이 클레임을 다 채울 때까지 기다린다 → 큐를 비운다 → 메시지 30건 발행
→ 30건을 다 끝내거나 70초가 지날 때까지 0.1초마다 처리 수를 본다 → 남은 메시지가 계속 돌지 않게 큐를 비운다.
결과는 화면에 출력하고 results/scenario-<이름>.txt에도 남긴다.

  필요한 커넥션         원문 공식 Tn × (Cm − 1) + 1. Tn은 동시 처리 수, Cm은 이력 저장이 REQUIRES_NEW면 2, 아니면 1
  걸린 시간            발행을 시작해서 30건째 처리를 끝낼 때까지
  커넥션을 기다린 시간   HikariCP가 커넥션을 빌려주기까지 걸린 시간(hikaricp.connections.acquire).
                     watch.sh의 pending은 1초마다 갱신되는 값이라 짧은 기다림은 잡히지 않아서 이 값을 본다.
                     최대는 최근 2분 동안의 값이라 매번 앱을 새로 띄운 뒤 돌린다

사용법: python3 scripts/scenario.py <이름>
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

COUNT = 30
LIMIT_SECONDS = 70
CLAIM_COUNT = 1000
QUEUE_URL = "http://localhost:9324/000000000000/notice-queue"


def request(url, method="GET"):
    with urllib.request.urlopen(urllib.request.Request(url, method=method), timeout=5) as response:
        return response.read()


def metric(name, statistic=None):
    # 통계를 고르지 않으면 첫 값을 쓴다 (카운터는 COUNT, 게이지는 VALUE)
    measurements = json.loads(request(f"http://localhost:8081/actuator/metrics/{name}"))["measurements"]
    return {m["statistic"]: m["value"] for m in measurements}[statistic] if statistic else measurements[0]["value"]


def compose_exec(service, *command):
    result = subprocess.run(["docker", "compose", "exec", "-T", service, *command], capture_output=True, text=True)
    return result.stdout.strip()


def ready():
    # 기동 직후에는 리스너가 클레임을 채우기 전에 메시지를 받아 "클레임 없음"으로 실패할 수 있어서, 클레임이 다 들어올 때까지 기다린다
    try:
        metric("notice.completed")
    except OSError:
        return False
    sql = "select count(*) from replay.claim"
    return compose_exec("mysql", "mysql", "-ureplay", "-preplay", "-N", "-e", sql) == str(CLAIM_COUNT)


def duration(seconds):
    return f"{seconds * 1000:.0f}ms" if seconds < 1 else f"{seconds:.1f}초"


def main(name):
    os.chdir(Path(__file__).resolve().parent.parent)
    for i in range(90):
        if ready():
            break
        if i == 0:
            print("앱이 뜰 때까지 기다린다...")
        time.sleep(2)

    tn = int(compose_exec("app", "printenv", "SPRING_CLOUD_AWS_SQS_LISTENER_MAXCONCURRENTMESSAGES"))
    pool = int(compose_exec("app", "printenv", "SPRING_DATASOURCE_HIKARI_MAXIMUMPOOLSIZE"))
    requires_new = compose_exec("app", "printenv", "REPLAY_HISTORYREQUIRESNEW") == "true"
    cm = 2 if requires_new else 1

    request(QUEUE_URL + "?Action=PurgeQueue")
    counters = ("notice.api.calls", "notice.completed", "hikaricp.connections.timeout")
    before = {key: metric(key) for key in counters}
    acquired_before = metric("hikaricp.connections.acquire", "COUNT")
    waited_before = metric("hikaricp.connections.acquire", "TOTAL_TIME")

    started = time.monotonic()
    request(f"http://localhost:8080/experiments/notices?count={COUNT}", method="POST")
    elapsed = None
    while time.monotonic() - started < LIMIT_SECONDS:
        if metric("notice.completed") - before["notice.completed"] >= COUNT:
            elapsed = time.monotonic() - started
            break
        time.sleep(0.1)

    api_calls, completed, timeouts = (int(metric(key) - before[key]) for key in counters)
    acquired = metric("hikaricp.connections.acquire", "COUNT") - acquired_before
    waited = metric("hikaricp.connections.acquire", "TOTAL_TIME") - waited_before
    waited_max = metric("hikaricp.connections.acquire", "MAX")
    request(QUEUE_URL + "?Action=PurgeQueue")

    history = "REQUIRES_NEW" if requires_new else "바깥 트랜잭션에 참여"
    lines = [
        f"== {name} ({time.strftime('%H:%M:%S')})",
        f"설정: 동시 처리(Tn) {tn}, 커넥션 풀 {pool}, 이력 저장 {history}(Cm {cm}) → 필요한 커넥션 {tn * (cm - 1) + 1}",
        f"처리: {COUNT}건 중 {completed}건, " + (duration(elapsed) if elapsed else f"{LIMIT_SECONDS}초 안에 끝나지 않음"),
        f"알림톡: {api_calls}번 나감 (처리를 끝낸 알림 {completed}건)",
        f"커넥션 획득 타임아웃: {timeouts}건",
        f"커넥션을 기다린 시간: 최대 {duration(waited_max)}, 평균 {duration(waited / acquired if acquired else 0)}",
    ]
    print("\n".join(lines))
    Path("results").mkdir(exist_ok=True)
    Path(f"results/scenario-{name}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])
