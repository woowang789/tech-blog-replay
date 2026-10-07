#!/usr/bin/env bash
# 로그 수집기(pv)를 멈추거나, 다시 움직이거나, 읽는 속도를 바꾼다.
#   pause       : 수집기 정지 → 앱 stdout 파이프가 곧 가득 찬다
#   resume      : 수집기 재개
#   rate <속도> : 초당 읽는 바이트 수 변경 (예: 16k, 64k, 1m)
set -euo pipefail
cd "$(dirname "$0")/.."

case "${1:-}" in
	pause) docker compose exec -T app pkill -STOP -x pv && echo "수집기 정지 ($(date +%H:%M:%S))" ;;
	resume) docker compose exec -T app pkill -CONT -x pv && echo "수집기 재개 ($(date +%H:%M:%S))" ;;
	rate)
		speed="${2:?usage: $0 rate <속도, 예: 16k>}"
		docker compose exec -T app sh -c "pv --remote \$(pgrep -x pv) --rate-limit $speed" \
			&& echo "수집기 속도 → 초당 $speed ($(date +%H:%M:%S))"
		;;
	*) echo "usage: $0 pause|resume|rate <속도>" >&2; exit 1 ;;
esac
