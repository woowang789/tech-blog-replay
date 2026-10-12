#!/usr/bin/env bash
# 2단계: 지금 이 순간의 층별 증거를 results/evidence-시각/에 모으고, 층끼리 맞춰 본 요약을 출력한다.
#   threads.txt  스레드 덤프 (jcmd Thread.print -l)
#   hikari.txt   HikariCP 지표
#   mysql.tsv    MySQL에서 본 앱 커넥션: 커넥션 번호, 상태(Command), 그 상태로 지난 초, 열린 트랜잭션의 나이(초), 실행 중인 쿼리
#   queue.txt    SQS 큐 상태
set -euo pipefail
cd "$(dirname "$0")/.."

out="results/evidence-$(date +%H%M%S)"
mkdir -p "$out"

docker compose exec -T app jcmd 1 Thread.print -l > "$out/threads.txt"

for name in active idle pending total timeout; do
	metric="hikaricp.connections.$name"
	[ "$name" = total ] && metric="hikaricp.connections"
	value=$(curl -s --max-time 2 "localhost:8081/actuator/metrics/$metric" \
		| python3 -c 'import json,sys; print(int(json.load(sys.stdin)["measurements"][0]["value"]))' 2>/dev/null || echo "?")
	echo "$name $value"
done > "$out/hikari.txt"

docker compose exec -T mysql mysql -uroot -proot -N -B -e "
	select p.id, p.command, p.time,
		ifnull(timestampdiff(second, t.trx_started, now()), ''),
		ifnull(p.info, '')
	from performance_schema.processlist p
	left join information_schema.innodb_trx t on t.trx_mysql_thread_id = p.id
	where p.user = 'replay'
	order by p.id" 2>/dev/null > "$out/mysql.tsv"

./scripts/queue.sh status > "$out/queue.txt"

echo "저장: $out"
python3 scripts/evidence_report.py "$out"
