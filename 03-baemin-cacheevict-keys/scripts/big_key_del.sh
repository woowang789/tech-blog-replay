#!/usr/bin/env bash
# 3단계 3-E: 값이 큰 키 하나(필드 100만 개짜리 해시)를 DEL로 지울 때, Redis가 메모리 해제를 백그라운드로 미루는지
# (lazyfree-lazy-user-del no / yes) 비교한다. 실험이 쓰는 db 0을 건드리지 않게 db 1에서 하고, 끝나면 설정을 처음대로 되돌린다.
#   DEL 응답까지         redis-cli가 DEL을 보내고 답을 받기까지 걸린 시간
#   백그라운드로 넘긴 객체  INFO memory의 lazyfreed_objects가 는 만큼. 해제를 백그라운드 스레드로 넘긴 값의 수다
# 사용법: ./scripts/big_key_del.sh
set -euo pipefail
cd "$(dirname "$0")/.."

docker compose exec -T redis sh -c '
original=$(redis-cli CONFIG GET lazyfree-lazy-user-del | tail -1)
for mode in no yes; do
  redis-cli CONFIG SET lazyfree-lazy-user-del $mode > /dev/null
  for i in $(seq 1 1000000); do echo "HSET big f$i v"; done | redis-cli -n 1 --pipe > /dev/null
  before=$(redis-cli INFO memory | grep "^lazyfreed_objects:" | tr -d "\r" | cut -d: -f2)
  start=$(date +%s%N); redis-cli -n 1 DEL big > /dev/null; end=$(date +%s%N)
  sleep 1
  after=$(redis-cli INFO memory | grep "^lazyfreed_objects:" | tr -d "\r" | cut -d: -f2)
  echo "lazyfree-lazy-user-del $mode: 필드 100만 개 해시 하나 DEL 응답까지 $(( (end - start) / 1000000 ))ms, 백그라운드로 넘긴 객체 $((after - before))개"
done
redis-cli CONFIG SET lazyfree-lazy-user-del "$original" > /dev/null'
