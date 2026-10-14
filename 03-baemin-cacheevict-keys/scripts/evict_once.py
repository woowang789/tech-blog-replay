"""3단계 3-D 실행기: 부하 없이 전체 삭제를 한 번 부르고, 성공했는지와 캐시가 실제로 비었는지 본다.
KEYS를 막아 둔 Redis(REDIS_KEYS_COMMAND=)에서 경로(동기·비동기)와 전략(KEYS·SCAN)마다 무슨 일이 생기는지 보려고 쓴다.

Redis를 비우고 products 캐시를 N개 채운다 → 전체 삭제 API를 부른다 → 2초 기다린다
→ 응답, 남은 캐시 키 수, 그동안 앱 로그에 남은 오류를 출력한다. 결과는 results/evict-once-<이름>.txt에도 남긴다.

사용법: python3 scripts/evict_once.py <이름> [캐시 키 수, 기본 1000]
"""
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from scenario import current_settings, describe_settings, redis, request, wait_ready

WAIT_SECONDS = 2


def evict_all():
    # 전체 삭제 API를 부르고 (HTTP 상태, 걸린 시간, 응답 본문)을 돌려준다. 실패 응답도 그대로 받는다
    started = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request("http://localhost:8080/experiments/evict-all", method="POST"),
                                    timeout=120) as response:
            status, body = response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        status, body = error.code, error.read().decode()
    return status, time.time() - started, body


def main(name, count):
    os.chdir(Path(__file__).resolve().parent.parent)
    wait_ready()
    settings = current_settings()

    redis("FLUSHALL")
    request(f"http://localhost:8080/experiments/seed?count={count}", method="POST", timeout=600)
    before = int(redis("DBSIZE"))
    since = datetime.fromtimestamp(time.time() - 1, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    status, took, body = evict_all()
    time.sleep(WAIT_SECONDS)
    after = int(redis("DBSIZE"))
    log = subprocess.run(["docker", "compose", "logs", "app", "--no-log-prefix", "--since", since],
                         capture_output=True, text=True).stdout
    errors = [line for line in log.splitlines() if "ERROR" in line or "Exception" in line]

    lines = [
        f"== {name} ({time.strftime('%H:%M:%S')})",
        f"설정: {describe_settings(settings)}",
        f"전체 삭제 API: HTTP {status}, {took * 1000:.0f}ms, 응답 본문 {body[:200]}",
        f"products 캐시 키: 삭제 전 {before:,}개 → {WAIT_SECONDS}초 뒤 {after:,}개",
        f"앱 로그의 오류 (전체 삭제를 부른 뒤): {len(errors)}줄",
    ]
    lines += [f"  {line[:220]}" for line in errors[:8]]
    print("\n".join(lines))
    Path("results").mkdir(exist_ok=True)
    Path(f"results/evict-once-{name}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 1000)
