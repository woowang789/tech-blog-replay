#!/usr/bin/env bash
# 4-B: 운영 중에 "에러 로그 폭주"를 켜거나 끈다. 켜면 요청마다 ERROR 로그 한 건을 스택 트레이스와 함께 남긴다.
# debug.sh처럼 관리 포트(8081)를 써서 장애 중에도 끌 수 있다.
set -euo pipefail

case "${1:-}" in
	on) enabled=true ;;
	off) enabled=false ;;
	*) echo "usage: $0 on|off" >&2; exit 1 ;;
esac

curl -sf -X POST localhost:8081/actuator/errorstorm \
	-H 'Content-Type: application/json' -d "{\"enabled\":$enabled}" > /dev/null
echo "에러 로그 폭주 → $1 ($(date +%H:%M:%S))"
