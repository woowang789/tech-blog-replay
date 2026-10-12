#!/usr/bin/env bash
# 앱의 스레드 덤프를 results/thread-dump-시각.txt에 저장하고, SQS 리스너 스레드가 무엇을 기다리는지 센다.
# 앱 컨테이너에서 java가 PID 1이라 jcmd 1로 뜬다. -l을 붙여야 스레드가 쥔 락까지 나온다.
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p results
out="results/thread-dump-$(date +%H%M%S).txt"
docker compose exec -T app jcmd 1 Thread.print -l > "$out"
echo "저장: $out"
python3 scripts/thread_dump_summary.py "$out"
