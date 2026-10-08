#!/usr/bin/env bash
# 지금 이 순간의 증거를 층마다 모아 results/evidence-시각/에 저장하고, 층끼리 맞춰 본 요약을 출력한다.
#   threads.txt : JVM 스레드 덤프 (jcmd Thread.print -l)
#   kernel.tsv  : 커널이 보는 java 스레드 (tid, 이름, 상태, 잠든 위치 wchan, 실행 중인 시스템 콜)
#   hikari.txt  : HikariCP 커넥션 풀 메트릭
#   mysql.tsv   : MySQL의 열린 트랜잭션과 앱 커넥션 상태
set -euo pipefail
cd "$(dirname "$0")/.."

dir="results/evidence-$(date +%H%M%S)"
mkdir -p "$dir"

docker compose exec -T app sh -c 'jcmd $(pgrep -x java) Thread.print -l' > "$dir/threads.txt"

docker compose exec -T app sh -c '
uname -m > /tmp/arch
J=$(pgrep -x java)
for t in /proc/$J/task/*; do
	state=$(sed "s/.*) //" "$t/stat" 2>/dev/null | cut -d" " -f1) || continue
	printf "%s\t%s\t%s\t%s\t%s\n" "$(basename "$t")" "$(cat "$t/comm" 2>/dev/null)" "$state" \
		"$(cat "$t/wchan" 2>/dev/null)" "$(cut -d" " -f1-2 "$t/syscall" 2>/dev/null)"
done' > "$dir/kernel.tsv"
docker compose exec -T app cat /tmp/arch > "$dir/arch.txt"

for m in active idle pending timeout; do
	v=$(curl -s --max-time 2 "localhost:8081/actuator/metrics/hikaricp.connections.$m" \
		| python3 -c 'import json,sys; print(int(json.load(sys.stdin)["measurements"][0]["value"]))')
	echo "$m=$v"
done > "$dir/hikari.txt"

docker compose exec -T mysql mysql -uroot -proot -N -B -e "
select 'trx', trx_mysql_thread_id, timestampdiff(second, trx_started, now()), trx_is_read_only, coalesce(trx_query, '')
from information_schema.innodb_trx;
select 'conn', id, command, time, coalesce(state, '')
from information_schema.processlist where user = 'replay';" 2>/dev/null > "$dir/mysql.tsv"

echo "저장: $dir"
python3 scripts/evidence_report.py "$dir"
