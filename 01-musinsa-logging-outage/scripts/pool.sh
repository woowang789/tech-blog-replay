#!/usr/bin/env bash
# 1초마다 HikariCP 커넥션 풀과 Tomcat 스레드 상태를 출력한다.
# API와 분리된 관리 포트(8081)를 쓰기 때문에 장애 중에도 조회된다.
set -uo pipefail

metric() {
	curl -s --max-time 2 "localhost:8081/actuator/metrics/$1" \
		| python3 -c 'import json,sys; print(int(json.load(sys.stdin)["measurements"][0]["value"]))' 2>/dev/null \
		|| echo "?"
}

printf "%-8s %7s %5s %8s %13s %12s\n" time active idle pending timeoutTotal tomcatBusy
while true; do
	printf "%-8s %7s %5s %8s %13s %12s\n" "$(date +%H:%M:%S)" \
		"$(metric hikaricp.connections.active)" \
		"$(metric hikaricp.connections.idle)" \
		"$(metric hikaricp.connections.pending)" \
		"$(metric hikaricp.connections.timeout)" \
		"$(metric tomcat.threads.busy)"
	sleep 1
done
