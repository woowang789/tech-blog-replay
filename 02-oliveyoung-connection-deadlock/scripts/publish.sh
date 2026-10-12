#!/usr/bin/env bash
# 알림 메시지를 N건 SQS에 한꺼번에 넣는다. 원문에서 각 비즈니스 로직이 알림 발송을 요청하는 부분이다.
# 사용법: ./scripts/publish.sh [건수, 기본 10]
set -euo pipefail

count="${1:-10}"
curl -sf -X POST "localhost:8080/experiments/notices?count=$count" > /dev/null
echo "메시지 ${count}건 발행 ($(date +%H:%M:%S))"
