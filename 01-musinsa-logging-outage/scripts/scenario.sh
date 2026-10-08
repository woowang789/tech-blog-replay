#!/usr/bin/env bash
# 3단계 공통 실행기: 지금 떠 있는 앱 설정 그대로 1-B와 같은 장애 조건을 자동으로 돌린다.
#   초당 50건 부하 100초. 부하 시작 15초 뒤 DEBUG를 켜고 60초 뒤 끈다.
# 출력 방식을 바꿔 띄운 뒤 이름만 바꿔 실행한다. 결과는 results/compare-<이름>/에 남는다.
#   meta.txt                실행 시각, 앱 설정, 로그 이벤트 수
#   k6.csv, k6-summary.txt  요청별 응답 시간과 상태
#   pool.txt                1초마다 커넥션 풀과 Tomcat 스레드 (pool.sh 출력)
#   app.log                 이번 실행 동안 수집기를 지나 실제로 출력된 로그
# 사용법: ./scripts/scenario.sh <이름>
set -uo pipefail
cd "$(dirname "$0")/.."

name="${1:?usage: $0 <이름>}"
out="results/compare-$name"
mkdir -p "$out"

metric() {
	curl -s --max-time 2 "localhost:8081/actuator/metrics/$1" \
		| python3 -c 'import json,sys; print(int(json.load(sys.stdin)["measurements"][0]["value"]))' 2>/dev/null \
		|| echo "?"
}

# 로그 이벤트 수를 먼저 읽고 시작 시각을 밀리초까지 남긴다. 출력된 줄은 로그에 찍힌 시각이 이 뒤인 것만 센다
events_before=$(metric logback.events)
start=$(python3 -c 'import time; print(f"{time.time():.3f}")')
{
	echo "name=$name"
	echo "start=$start"
	echo "logging=$(curl -s localhost:8080/experiments/logging-config)"
	docker compose exec -T app sh -c 'env | sort | grep -E "^(LOG_CONSUMER_RATE|SPRING_PROFILES_ACTIVE|OTEL_AGENT|REPLAY_)"'
	echo "events_before=$events_before"
} > "$out/meta.txt"

echo "== $name: 부하 100초 (15초 뒤 DEBUG를 켜고 60초 뒤 끈다)"
./scripts/pool.sh > "$out/pool.txt" 2>&1 &
pool_pid=$!
disown "$pool_pid"
RATE=50 DURATION=100s k6 run --quiet --out csv="$out/k6.csv" k6/load.js > "$out/k6-summary.txt" 2>&1 &
k6_pid=$!
sleep 15
echo "debug_on=$(date +%s)" >> "$out/meta.txt"
./scripts/debug.sh on
sleep 60
echo "debug_off=$(date +%s)" >> "$out/meta.txt"
./scripts/debug.sh off
wait "$k6_pid"
kill "$pool_pid"

# 밀린 로그를 빨리 내보낸 뒤, 이번 실행 동안 실제로 출력된 줄을 모은다
rate=$(docker compose exec -T app printenv LOG_CONSUMER_RATE)
./scripts/consumer.sh rate 100m > /dev/null
until [ "$(metric tomcat.threads.busy)" = "0" ]; do sleep 1; done
sleep 3
./scripts/consumer.sh rate "$rate" > /dev/null
echo "events_after=$(metric logback.events)" >> "$out/meta.txt"
docker compose logs app --no-log-prefix --since "$(( ${start%.*} - 10 ))" > "$out/app.log"

python3 scripts/compare_report.py "$out"
