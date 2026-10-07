#!/usr/bin/env bash
# 운영 중에 애플리케이션 패키지의 DEBUG 로그를 켜거나 끈다 (actuator loggers 엔드포인트).
set -euo pipefail

case "${1:-}" in
	on) level=DEBUG ;;
	off) level=INFO ;;
	*) echo "usage: $0 on|off" >&2; exit 1 ;;
esac

curl -sf -X POST localhost:8081/actuator/loggers/replay.loggingoutage \
	-H 'Content-Type: application/json' -d "{\"configuredLevel\":\"$level\"}"
echo "replay.loggingoutage → $level ($(date +%H:%M:%S))"
