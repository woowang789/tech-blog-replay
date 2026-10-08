#!/usr/bin/env bash
# 4-A: 가상 스레드까지 들어간 스레드 덤프를 뜬다.
# jcmd Thread.print(thread-dump.sh)는 플랫폼 스레드만 보여 줘서, 가상 스레드로 처리 중인 요청은 하나도 나오지 않는다.
# 그래서 jcmd Thread.dump_to_file로 컨테이너 안에 쓴 뒤 results/vthread-dump-시각.txt로 가져오고, 가상 스레드가 어디서 멈췄는지 센다.
# 이 형식에는 락 주소가 없어서 대기 위치는 스택에 있는 메서드로 가른다.
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p results
out="results/vthread-dump-$(date +%H%M%S).txt"
docker compose exec -T app sh -c 'f=/tmp/vthread-dump.txt; rm -f "$f"; jcmd $(pgrep -x java) Thread.dump_to_file "$f" > /dev/null && cat "$f"' > "$out"
echo "저장: $out"

awk 'BEGIN { RS = "" }
/^#[0-9]+ "[^"]*" virtual\n/ {
	total++
	holding = /ProductService\.getProduct/
	failing = /SqlExceptionHelper|GlobalExceptionHandler/
	if (/FileOutputStream\.writeBytes/) write++
	else if (/OutputStreamAppender/ && /ReentrantLock\.lock/) { lock++; if (holding) lock_holding++; else if (failing) lock_failing++ }
	else if (/HikariPool\.getConnection/) conn++
	else other++
}
END {
	printf "가상 스레드 %d개\n", total
	printf "  1) stdout write에서 멈춤                : %4d개\n", write
	printf "  2) 로그 출력 락 대기 (streamWriteLock) : %4d개 (커넥션 보유 %d개, 타임아웃 뒤 실패 로그 %d개)\n", lock, lock_holding, lock_failing
	printf "  3) DB 커넥션 대기                      : %4d개\n", conn
	printf "  그 밖                                  : %4d개\n", other
}' "$out"
