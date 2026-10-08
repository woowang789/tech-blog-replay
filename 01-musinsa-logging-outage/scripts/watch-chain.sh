#!/usr/bin/env bash
# 장애 연쇄의 각 층을 1초 간격으로 나란히 출력한다.
#   collector    : 로그 수집기(pv) 상태. STOPPED = SIGSTOP을 받아 멈춘 상태
#   writeBlocked : 커널에서 stdout(fd 1)에 write 하다 잠든 java 스레드 수
#   active ~ tomcatBusy : HikariCP 커넥션 풀(timeoutTotal은 누적)과 요청 처리 중인 Tomcat 스레드
#   openTrx ~ runningSql : MySQL에서 본 열린 트랜잭션 수, 가장 오래된 트랜잭션의 나이, 실제로 쿼리를 실행 중인 트랜잭션 수
set -uo pipefail
cd "$(dirname "$0")/.."

metric() {
	curl -s --max-time 2 "localhost:8081/actuator/metrics/$1" \
		| python3 -c 'import json,sys; print(int(json.load(sys.stdin)["measurements"][0]["value"]))' 2>/dev/null \
		|| echo "?"
}

# 컨테이너 안에서 실행: pv 상태와, 시스템 콜 번호가 write이고 첫 인자(fd)가 1인 java 스레드 수
KERNEL_PROBE='
J=$(pgrep -x java); P=$(pgrep -x pv)
case "$(uname -m)" in aarch64) NR=64 ;; *) NR=1 ;; esac
state=$(sed "s/.*) //" /proc/$P/stat | cut -d" " -f1)
n=0
for t in /proc/$J/task/*; do
	read -r nr fd _ < "$t/syscall" 2>/dev/null || continue
	[ "$nr" = "$NR" ] && [ "$fd" = "0x1" ] && n=$((n + 1))
done
echo "$state $n"
'

MYSQL_PROBE="select count(*), coalesce(max(timestampdiff(second, trx_started, now())), 0), coalesce(sum(trx_query is not null), 0) from information_schema.innodb_trx"

printf "%-8s %9s %12s %6s %7s %12s %10s %7s %9s %10s\n" \
	time collector writeBlocked active pending timeoutTotal tomcatBusy openTrx oldestTrx runningSql
while true; do
	read -r pv_state writers <<<"$(docker compose exec -T app sh -c "$KERNEL_PROBE" 2>/dev/null)"
	read -r trx age running <<<"$(docker compose exec -T mysql mysql -uroot -proot -N -B -e "$MYSQL_PROBE" 2>/dev/null)"
	[ "${pv_state:-}" = "T" ] && collector="STOPPED" || collector="running"
	printf "%-8s %9s %12s %6s %7s %12s %10s %7s %9s %10s\n" "$(date +%H:%M:%S)" \
		"$collector" "${writers:-?}" \
		"$(metric hikaricp.connections.active)" "$(metric hikaricp.connections.pending)" \
		"$(metric hikaricp.connections.timeout)" "$(metric tomcat.threads.busy)" \
		"${trx:-?}" "${age:-?}s" "${running:-?}"
	sleep 1
done
