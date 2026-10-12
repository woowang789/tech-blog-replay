#!/usr/bin/env bash
# 1초마다 SQS 큐, 커넥션 풀, 알림 처리 상태를 한 줄씩 출력한다.
#   queued     큐에서 처리를 기다리는 메시지 수 (ApproximateNumberOfMessages)
#   inFlight   리스너가 가져가서 처리 중인 메시지 수 (ApproximateNumberOfMessagesNotVisible)
#   active, idle, pending   HikariCP: 빌려 간 커넥션, 놀고 있는 커넥션, 커넥션을 기다리는 스레드
#   timeouts   커넥션을 30초 안에 못 빌려 실패한 누적 횟수
#   apiCalls   알림톡을 실제로 보낸 누적 횟수 (가짜 Messaging API 호출)
#   completed  알림 내역까지 저장해 처리를 끝낸 누적 횟수
# 관리 포트(8081)를 써서 장애 중에도 조회된다.
set -uo pipefail

QUEUE_URL="localhost:9324/000000000000/notice-queue"

metric() {
	curl -s --max-time 2 "localhost:8081/actuator/metrics/$1" \
		| python3 -c 'import json,sys; print(int(json.load(sys.stdin)["measurements"][0]["value"]))' 2>/dev/null \
		|| echo "?"
}

queue() {
	local value
	value=$(curl -s --max-time 2 "$QUEUE_URL?Action=GetQueueAttributes&AttributeName.1=$1" \
		| sed -n 's|.*<Value>\(.*\)</Value>.*|\1|p' | head -1)
	echo "${value:-?}"
}

printf "%-8s %6s %8s %6s %4s %7s %8s %8s %9s\n" time queued inFlight active idle pending timeouts apiCalls completed
while true; do
	printf "%-8s %6s %8s %6s %4s %7s %8s %8s %9s\n" "$(date +%H:%M:%S)" \
		"$(queue ApproximateNumberOfMessages)" \
		"$(queue ApproximateNumberOfMessagesNotVisible)" \
		"$(metric hikaricp.connections.active)" \
		"$(metric hikaricp.connections.idle)" \
		"$(metric hikaricp.connections.pending)" \
		"$(metric hikaricp.connections.timeout)" \
		"$(metric notice.api.calls)" \
		"$(metric notice.completed)"
	sleep 1
done
