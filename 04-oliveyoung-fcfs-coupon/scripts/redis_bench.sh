#!/usr/bin/env bash
# 3단계 3-D: Redis 혼자서는 명령을 초당 몇 번 처리하나. 앱·MQ·DB를 빼고 Redis 쪽 비용만 본다.
# redis-benchmark(Redis에 들어 있음)로 GET, INCR, 원문의 Lua 스크립트(EVALSHA)를 각각 재고,
# 방식마다 요청 1건이 Redis에 시키는 명령을 더해 "요청 1건의 Redis 처리 시간"을 어림한다.
#   원문 기존      앞단 GET + 워커 GET + 워커 INCR    (3번)
#   시도 1 선차감   앞단 GET + INCR                   (2번)
#   시도 2 Lua     앞단 EVALSHA 하나                  (1번. 스크립트 안에서 GET·INCR을 한다)
#   시도 3 이중 카운터  앞단 INCR countReq + INCR count  (2번)
# 실험이 쓰는 db 0을 건드리지 않게 db 1에서 하고, 끝나면 db 1을 비운다.
# 사용법: ./scripts/redis_bench.sh [요청 수, 기본 200000] [동시 연결 수, 기본 50]
set -euo pipefail
cd "$(dirname "$0")/.."
requests=${1:-200000}
clients=${2:-50}

docker compose exec -T redis sh -c "
script=\$(cat <<'LUA'
local current = redis.call('GET', KEYS[1])
if current then
    local num = tonumber(current)
    if num and num < tonumber(ARGV[1]) then
        redis.call('INCR', KEYS[1])
        return true
    else
        return false
    end
else
    redis.call('SET', KEYS[1], 1)
    redis.call('EXPIREAT', KEYS[1], tonumber(ARGV[2]))
    return true
end
LUA
)
sha=\$(redis-cli -n 1 SCRIPT LOAD \"\$script\")
redis-cli -n 1 SET bench:count 0 > /dev/null
echo \"요청 $requests번, 동시 연결 $clients개 (db 1)\"
get=\$(redis-benchmark -n $requests -c $clients -q --csv -n $requests GET bench:count | tail -1 | cut -d, -f2 | tr -d '\"')
incr=\$(redis-benchmark -n $requests -c $clients -q --csv INCR bench:count | tail -1 | cut -d, -f2 | tr -d '\"')
eval=\$(redis-benchmark -n $requests -c $clients -q --csv EVALSHA \$sha 1 bench:count 100000000 4102444800 | tail -1 | cut -d, -f2 | tr -d '\"')
redis-cli -n 1 FLUSHDB > /dev/null
awk -v get=\"\$get\" -v incr=\"\$incr\" -v eval=\"\$eval\" 'BEGIN {
  printf \"  %-22s 초당 %9.0f번  (1번에 %.1fµs)\\n\", \"GET\", get, 1000000 / get
  printf \"  %-22s 초당 %9.0f번  (1번에 %.1fµs)\\n\", \"INCR\", incr, 1000000 / incr
  printf \"  %-22s 초당 %9.0f번  (1번에 %.1fµs)\\n\", \"EVALSHA(원문 스크립트)\", eval, 1000000 / eval
  print \"요청 1건이 Redis에 시키는 일 (1번 처리 시간의 합, µs)\"
  printf \"  원문 기존 (GET + GET + INCR)       %.1f\\n\", 2000000 / get + 1000000 / incr
  printf \"  시도 1 선차감 (GET + INCR)          %.1f\\n\", 1000000 / get + 1000000 / incr
  printf \"  시도 2 Lua (EVALSHA)               %.1f\\n\", 1000000 / eval
  printf \"  시도 3 이중 카운터 (INCR + INCR)    %.1f\\n\", 2000000 / incr
}'
"
