#!/usr/bin/env bash
# 3단계: traceparent 헤더를 붙여 요청을 보내고, 그 요청이 남긴 로그에 보낸 trace_id가 그대로 찍혔는지 센다.
# 앱을 OTEL_AGENT=on, SPRING_PROFILES_ACTIVE=trace(또는 trace,async / trace,trace-aware)로 띄운 상태에서 쓴다.
# 사용법: ./scripts/trace-check.sh [요청 수, 기본 20]
set -euo pipefail
cd "$(dirname "$0")/.."

count="${1:-20}"
since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
sent=()
for i in $(seq 1 "$count"); do
	trace=$(openssl rand -hex 16)
	curl -sf -o /dev/null -H "traceparent: 00-$trace-$(openssl rand -hex 8)-01" "localhost:8080/products/$i"
	sent+=("$trace")
done
sleep 2 # 비동기 출력과 수집기가 로그를 내보낼 시간을 준다

logs=$(docker compose logs app --no-log-prefix --since "$since" | grep "상품 조회 id=" || true)
matched=0
for trace in "${sent[@]}"; do
	if grep -q "trace_id=$trace" <<<"$logs"; then
		matched=$((matched + 1))
	fi
done

echo "프로필: $(docker compose exec -T app printenv SPRING_PROFILES_ACTIVE), 에이전트: $(docker compose exec -T app printenv OTEL_AGENT)"
echo "요청 ${count}건 → 상품 조회 로그 $(grep -c "상품 조회" <<<"$logs" || true)줄"
echo "  보낸 trace_id가 그대로 찍힌 줄: ${matched}"
echo "  trace_id가 빈 값인 줄:          $(grep -c "trace_id= " <<<"$logs" || true)"
echo "[예시]"
head -2 <<<"$logs" | cut -c1-220
