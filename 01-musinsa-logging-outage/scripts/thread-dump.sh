#!/usr/bin/env bash
# 스레드 덤프를 떠서 results/에 저장하고, 스레드들이 어디서 멈춰 있는지 분류해 보여 준다.
# -l: 스레드가 쥐고 있는 락(ReentrantLock 등)까지 함께 출력
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p results
out="results/thread-dump-$(date +%H%M%S).txt"
docker compose exec -T app sh -c 'jcmd $(pgrep -x java) Thread.print -l' > "$out"
echo "저장: $out"
python3 scripts/thread_dump_summary.py "$out"
