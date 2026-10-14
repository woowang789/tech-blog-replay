# 03. 배민 「이제 Redis를 멈춰보겠습니다: @CacheEvict 파헤치기」 재현

> 원문: [이제 Redis를 멈춰보겠습니다: @CacheEvict 파헤치기](https://techblog.woowahan.com/23138/) (우아한형제들 기술블로그, 2025-11-04)

## 원문 요약

- **문제:** `@CacheEvict(allEntries = true)`는 캐시 하나를 통째로 지운다. Spring Data Redis는 이때 기본 전략으로 `KEYS 캐시이름::*`를 보내 지울 키를 모두 찾고, 찾은 키를 `DEL` 한 번으로 지운다. `KEYS`는 DB의 모든 키를 훑는 O(N) 명령이라, 싱글 스레드인 Redis가 그동안 다른 요청을 처리하지 못한다. 키가 많으면 `DEL`의 메모리 해제도 Redis를 붙잡는다.
- **경로:** `@CacheEvict(allEntries = true)` → `CacheEvictOperation`(cacheWide) → `CacheAspectSupport.performCacheEvicts` → `doClear` → `RedisCache.clear()` → `RedisCacheWriter.clean(name, "name::*")` → `BatchStrategy.cleanCache` → `BatchStrategies.Keys`: `KEYS` 후 `DEL`.
- **왜 기본값이 KEYS인가:** `KEYS`는 모든 드라이버와 운영 모드(Standalone, Cluster)에서 동작한다. `SCAN`은 Lettuce에서만 완전히 지원되고 Jedis는 클러스터가 아닐 때만 지원한다. Spring Boot 자동 설정은 `RedisCacheWriter.nonLockingRedisCacheWriter(connectionFactory)`를 쓰고, 이것이 `BatchStrategies.keys()`를 고른다.
- **대응:** `RedisCacheManagerBuilderCustomizer`로 캐시 쓰기 도구를 `BatchStrategies.scan(n)`으로 바꿨다. 다만 다음 한계가 있다.
  - 잠금을 쓰는 캐시 쓰기 도구(`lockingRedisCacheWriter`)면 `SCAN`이어도 지우는 동안 막힌다.
  - `SCAN`도 결국 전체 키 탐색이다. 원문에서는 캐시가 많아 API 타임아웃(60초)이 났다.
- **원문의 결론:** 운영에서는 `allEntries = true`를 쓰지 않는 것이 좋다. 전체 삭제가 꼭 필요하면 `SCAN`으로 도는 별도 로직을 만든다.
  - 운영 Redis는 `KEYS`를 막아 두는 경우가 많다(`rename-command KEYS ""`). 그러면 기본 전략에서 `RedisCommandExecutionException`이 난다.
  - 키가 많을 때는 `DEL` 대신 메모리 해제를 백그라운드로 미루는 `UNLINK`가 낫다(`lazyfree-lazy-user-del`). Valkey 8.0부터는 `DEL`이 기본으로 `UNLINK`처럼 동작한다.
- **원문 환경:** Spring Boot 3.3.7, Spring Data Redis 3.3.7, Lettuce 6.3.2. Redis 버전은 밝히지 않았다.

## 장애 연쇄

```
캐시가 크게 쌓인 상태에서 @CacheEvict(allEntries = true)가 불린다
  ▼ RedisCache.clear() → 캐시 쓰기 도구가 기본 전략으로 KEYS products::* 를 보낸다
  ▼ KEYS는 DB의 키를 모두 훑는다(O(N)). 싱글 스레드인 Redis는 그동안 다른 명령을 처리하지 못한다
  ▼ 찾은 키를 DEL 한 번으로 지운다. 키가 많으면 메모리 해제로 또 멈춘다
  ▼ 그동안 들어온 캐시 조회가 모두 기다린다 (서비스 지연, 타임아웃)
```

## 진행 단계

| 단계 | 내용 | 상태 |
|---|---|---|
| 0. 사전 확인 | 최신 버전(Spring Boot 4.1.1, Spring Data Redis 4.1.1, Redis 8.10.2)에서도 기본 전략이 `KEYS`이고, 전체 삭제가 Redis를 멈추는가 | ✅ 완료 |
| 1. 재현 | 상품 조회 부하 중에 전체 삭제를 부르면 다른 조회가 어떻게 되나. 원문처럼 동기로 지울 때(1-A)와 4.x 기본인 비동기로 지울 때(1-B) | ✅ 완료 |
| 2. 원인 증명 | 1단계의 멈춤이 Redis(`KEYS`·`DEL` 실행), 앱의 Redis 연결, 앱 JVM(GC) 중 어디서 생겼는지 증거로 가른다(2-A 동기, 2-C 비동기). `KEYS`가 DB의 모든 키를 훑는지 본다(2-B) | ✅ 완료 |
| 3. 해결책 재현 | 원문의 `SCAN` 전환(3-A)과 원문이 적은 두 한계(3-B 오래 걸림, 3-C 잠금), 원문의 조언(3-D `KEYS`를 막은 Redis, 3-E `DEL` 대신 `UNLINK`) | ✅ 완료 |
| 4. 원문 너머 | 필요하면 정한다 | |

## 실험 환경

```
k6 ─ 상품 조회 초당 200건 + 전체 삭제 1번 (1단계부터)
 │
 ▼
GET /products/{id}              상품 조회. @Cacheable("products")라 캐시에 없을 때만 가짜 DB(10ms)에서 읽는다
POST /experiments/seed?count=N  실험용: products 캐시를 N개로 채운다(@Cacheable과 같은 키·값 형식).
                                &cache=others면 다른 캐시(others::{id})를 채운다 (2단계부터)
POST /experiments/evict-all     원문의 @CacheEvict(cacheNames = "products", allEntries = true)
 │
 ▼
app 컨테이너 (Spring Boot, Lettuce, GC 로그) ─▶ Redis (RDB 스냅샷 끔, 6379 공개) ◀─ 증거 수집기 (2단계부터)
 캐시 키는 products::{id}, 값은 JDK 직렬화(105바이트)
```

| 구성 요소 | 버전 |
|---|---|
| Spring Boot | 4.1.1 |
| Spring Framework | 7.0.9 |
| Spring Data Redis | 4.1.1 |
| Lettuce | 7.5.2 |
| Redis | 8.10.2 |
| Java | 21 (Eclipse Temurin) |
| k6 | 2.2.0 (부하 도구, 로컬에 설치) |

| 스위치 | 뜻 |
|---|---|
| `CACHE_IMMEDIATE_WRITES` | `true`면 캐시 쓰기를 원문(Spring Data Redis 3.3.7)처럼 동기로 한다(`RedisCacheWriter`의 `immediateWrites()`). 기본은 `false`, 4.x 기본값이다(아래 0단계 결과 참고) |
| `CACHE_BATCH_STRATEGY` | `scan`이면 전체 삭제할 키를 `KEYS` 대신 `SCAN`으로 찾는다(`BatchStrategies.scan(n)`, 원문의 해결책). 기본은 `keys` (3단계) |
| `CACHE_SCAN_BATCH_SIZE` | `SCAN` 한 번에 가져오고(`COUNT`) 한 번에 지우는 키 수. 기본 1000 (3단계) |
| `CACHE_LOCKING` | `true`면 잠금을 쓰는 캐시 쓰기 도구로 바꾼다(`enableLocking()`). 기본 `false` (3단계) |
| `REDIS_LAZYFREE_USER_DEL` | `yes`면 Redis가 `DEL`도 `UNLINK`처럼 메모리 해제를 백그라운드로 미룬다(`lazyfree-lazy-user-del`). 기본 `no` (3단계) |
| `REDIS_KEYS_COMMAND` | 빈 값으로 주면(`REDIS_KEYS_COMMAND=`) Redis가 `KEYS`를 막는다(`rename-command KEYS ""`). 주지 않으면 그대로 (3단계) |

스위치는 `docker compose up -d` 앞에 붙여 준다. 붙이지 않은 스위치는 기본값으로 돌아간다.

## 0단계: 사전 확인 결과

- **원문의 경로가 그대로다.** Spring Data Redis 4.1.1 jar를 javap로 따라가 봤다.
  - `RedisCache.clear()`는 `clear("*")`를 거쳐 `RedisCacheWriter.clear(name, "products::*")`를 부른다. 원문(3.3.7)의 `clean`이 `clear`로 이름만 바뀌었다(`clean`은 `clear`를 부르는 기본 메서드로 남았다).
  - `RedisCacheWriter.nonLockingRedisCacheWriter(factory)`의 기본 전략은 여전히 `BatchStrategies.keys()`다. `Keys`는 `KEYS`로 찾고 `DEL`로 지운다.
  - Spring Boot 4.1.1의 자동 설정(`org.springframework.boot.cache.autoconfigure.RedisCacheConfiguration`)은 `RedisCacheManager.builder(factory)`를 쓴다. 이것이 `nonLockingRedisCacheWriter(factory)`로 이어져 기본 전략은 `KEYS`다. 전략을 바꾸는 `spring.cache.redis.*` 속성은 없다.
- **원문과 다른 점: 4.x는 Lettuce에서 전체 삭제가 비동기다.**
  - 4.x의 캐시 쓰기 도구는 `immediateWrites`가 기본으로 꺼져 있다. 그래서 반응형 연결을 쓸 수 있으면(Lettuce) 쓰기를 비동기로 한다.
  - 이때 `clear`는 반응형 연결로 `KEYS`를 보낸 뒤 찾은 키를 64개씩 `UNLINK`로 지운다. 이 일을 `CompletableFuture`로 맡겨 두고 결과를 기다리지 않는다. 그래서 `@CacheEvict`를 부른 스레드는 바로 돌아온다.
  - `immediateWrites()`를 켜거나 `invalidate()`(`@CacheEvict`의 `beforeInvocation = true`)로 가면 원문처럼 동기로 `KEYS` 후 `DEL` 한 번을 끝까지 기다린다(`invalidate`는 javap로만 확인).
  - 원문 버전 3.3.7은 이 비동기 쓰기가 없고 `clean`이 동기로 실행된다(3.3.7 jar를 javap로 확인).
  - 비동기 쓰기는 4.0.0부터 생겼다. 3.4.0, 3.5.0에는 없고 4.0.0부터 `immediateWrites` 설정이 기본 `false`로 들어왔다(각 jar를 javap로 확인). 전체 삭제(`clear`)만이 아니라 `put`(캐시 저장), `evict`(키 하나 삭제)도 비동기다. `putIfAbsent`와 `invalidate`는 동기 그대로다. 연결이 비동기를 지원하지 않는 Jedis에서는 4.x에서도 동기다.
- **Redis 8.10.2는 `lazyfree-lazy-user-del`이 `no`다.** `DEL`이 메모리 해제를 그 자리에서 한다. 원문이 말한 Valkey 8과 다르다.
- **재현 확인** (Claude 검증, `results/claude-verification/stage0/`)
  - **측정:** 캐시를 채운 뒤 전체 삭제를 불렀다. 그동안 Redis 안에서 10ms마다 PING 왕복 지연을 잰 최대값, 삭제 50ms 뒤 보낸 상품 조회 하나의 응답 시간, Redis가 명령별로 쓴 시간(`INFO commandstats`)을 봤다.

  | 캐시 키 | 경로 | 삭제 호출 | Redis가 쓴 시간 | Redis 안 PING 지연 최대 | 삭제 중 다른 조회 |
  |---|---|---|---|---|---|
  | 100만 | 4.x 기본(비동기) | 63ms | `KEYS` 213ms, `UNLINK` 15,625번(합 765ms) | 210ms | 0.26초 |
  | 300만 | 4.x 기본(비동기) | 7ms | `KEYS` 685ms, `UNLINK` 46,875번(합 3,471ms) | 687ms | 0.66초 |
  | 100만 | 원문처럼 동기 | 1.41초 | `KEYS` 227ms, `DEL` 한 번 483ms | 504ms | 0.37초 |
  | 300만 | 원문처럼 동기 | 3.94초 | `KEYS` 608ms, `DEL` 한 번 1,633ms | 1,699ms | 0.85초 |

  - **두 경로 모두 Redis가 멈췄다.** 비동기에서도 `KEYS`가 도는 동안 PING이 그만큼 기다렸고, 다른 조회도 기다렸다. 비동기는 삭제를 부른 쪽만 기다리지 않을 뿐이다. `UNLINK`는 64개씩 짧게 나뉘어 그 사이에 다른 명령이 끼어든다.
  - **동기에서는 `DEL` 한 번이 `KEYS`보다 오래 Redis를 붙잡았다.** 300만 개에서 1.6초였다.
  - **실행마다 시간이 꽤 달랐다.** 같은 조건에서 `KEYS`는 100만 개에 130~480ms, 300만 개에 540~730ms였다. 동기 `DEL`은 100만 개에 483~1,550ms였다. 앱 없이 Redis에서 `KEYS`만 돌린 값이 130ms, 538ms다.

## 1단계: 재현

원문은 `KEYS`의 위험을 "O(N)이라 Redis를 막는다"는 설명으로만 다뤘다. 그때 서비스가 어떻게 되는지는 재지 않았다(원문이 잰 것은 3단계에서 볼 `SCAN` 전환 뒤의 타임아웃이다). 이 단계에서는 상품 조회 부하를 걸어 둔 채 전체 삭제를 한 번 불러, 그동안 다른 조회가 어떻게 되는지 본다. 원문처럼 동기로 지우는 경로(1-A)와 4.x 기본인 비동기 경로(1-B)를 모두 본다.

### 준비

```bash
./gradlew bootJar
```

```bash
CACHE_IMMEDIATE_WRITES=true docker compose up -d --build
```

### 도구

| 파일 | 하는 일 |
|---|---|
| `k6/load.js` | 상품 조회를 초당 200건씩 40초 동안 보낸다(인기 상품 1,000개 중 하나). 20초째에 전체 삭제 API를 한 번 부른다. 조회는 응답이 느려져도 초당 보내는 수가 줄지 않는다 |
| `scripts/scenario.py <이름> [캐시 키 수]` | Redis를 비우고 캐시를 다시 채운 뒤(기본 100만 개) k6를 돌리고 요약한다. 결과는 `results/scenario-<이름>/`에 남는다(`report.txt`, 요청별 기록 `k6.csv`) |

- 한 번 돌리는 데 1분 남짓 걸린다. 캐시를 채우는 데 100만 개는 몇 초, 300만 개는 20초쯤 걸린다.
- k6는 처음 몇 초 동안 VU마다 새 연결을 열어 응답이 튈 수 있다. 그래서 처음 10초는 요약에서 뺀다.
- 실행기는 앞 실행이 남긴 키를 지우고 시작한다. 다음 중 하나라도 해당하면 요약 위에 `주의`를 출력한다. 그 결과는 버리고 다시 돌린다.
  - 채운 키 수와 삭제 전 Redis 키 수가 다르다.
  - Redis가 받은 `KEYS`가 1번이 아니다.
  - 앱 설정(동기·비동기)과 Redis가 받은 삭제 명령이 맞지 않는다.
  - k6가 조회를 제때 보내지 못했다.

요약 읽는 법

| 항목 | 뜻 |
|---|---|
| 시각 | 조회를 보낸 시각. 전체 삭제를 보낸 시각을 0으로 잡는다 |
| 조회가 멈췄다가 한꺼번에 풀린 때 | 100ms 넘게 걸린 조회가 응답을 기다리던 구간을 이어 붙였다. 평소 조회는 캐시에 있으면 수 ms, 없어서 가짜 DB(10ms)를 거쳐도 수십 ms 안이다 |
| 1초 표 | 1초마다 보낸 조회의 중앙값과 최대 |
| 0.1초 표의 `끝남` | 그 0.1초 동안 응답이 돌아온 조회 수. 평소에는 `보냄`과 비슷하게 20건 안팎이다 |
| 0.1초 표의 `최대 응답` | 그 0.1초에 보낸 조회 중 가장 오래 걸린 것 |
| Redis가 받은 명령 | k6가 도는 동안 Redis가 처리한 `KEYS`, `DEL`, `UNLINK` 수 |

### 실험 1-A: 원문처럼 동기로 지울 때

```bash
python3 scripts/scenario.py 1a-1m
```

```bash
python3 scripts/scenario.py 1a-3m 3000000
```

### 실험 1-B: 4.x 기본(비동기)으로 지울 때

스위치 없이 앱을 다시 띄운다.

```bash
docker compose up -d app
```

```bash
python3 scripts/scenario.py 1b-1m
```

```bash
python3 scripts/scenario.py 1b-3m 3000000
```

**관찰 포인트**
- 전체 삭제 API는 보내고 얼마 만에 응답하나? 1-A와 1-B가 어떻게 다른가?
- 조회가 멈췄다가 풀린 것은 몇 번이고, 각각 얼마나 이어졌나? 캐시 키를 3배로 늘리면 어떻게 되나?
- 0.1초 표에서 `끝남`이 0인 줄은 몇 줄 이어지나? 그 뒤 첫 줄의 `끝남`은 몇 건인가?
- 멈춘 구간의 `최대 응답` 막대는 어떤 모양인가? 왜 그런 모양일까?
- 삭제 뒤 1초 표의 중앙값은 몇 초 동안 어떻게 되나? 왜일까?
- Redis가 받은 명령은 1-A와 1-B가 어떻게 다른가?

### 생각해 볼 질문 (2단계에서 증명한다)

1. 1-A에서 조회가 두 번 멈춘다면 각각 무엇 때문일까? 1-B의 횟수는 왜 그럴까?
2. 1-B에서는 전체 삭제를 부른 스레드가 기다리지 않는다. 그런데 왜 다른 조회가 멈출까?
3. 조회가 멈춘 시간은 Redis가 그 명령을 실제로 실행한 시간과 같을까? 다르다면 나머지는 어디서 왔을까?
4. 1-B 300만 개에서 첫 멈춤 뒤에도 짧은 멈춤이 나온다면, Redis 탓일까 앱 탓일까?
5. `products` 캐시의 키는 1,000개뿐이고 Redis에 다른 키가 300만 개 있다면, `KEYS products::*`는 빨리 끝날까?

### 1단계 결과

직접 실행(2026-10-13 15:36~15:46)한 값이다. 네 번 모두 `주의` 없이 끝났다. Claude가 검증하며 돌린 값은 `results/claude-verification/stage1/`에 있다.

| 관찰 항목 | 1-A 100만 | 1-A 300만 | 1-B 100만 | 1-B 300만 |
|---|---|---|---|---|
| 전체 삭제 응답 | 1.88초 | 5.09초 | 40ms | 23ms |
| 조회가 멈췄다가 풀린 구간 (최대 응답) | +0.04~+0.52초 (477ms)<br>+0.75~+1.93초 (1.17초)<br>+13.30~+13.56초 (238ms) | +0.01~+1.16초 (1.13초)<br>+1.48~+1.85초 (362ms)<br>+2.03~+5.36초 (3.09초) | +0.04~+0.28초 (232ms) | +0.02~+1.35초 (1.30초)<br>+1.73~+1.98초 (239ms)<br>+10.59~+10.69초 (103ms) |
| 100ms 넘게 기다린 조회 | 318건 | 909건 | 28건 | 275건 |
| 가장 긴 멈춤이 풀린 0.1초에 온 응답 (평소 20건 안팎) | 245건 | 454건 | 52건 | 269건 |
| 삭제 뒤 1초 표 중앙값이 오른 구간 (평소 2ms) | +2~+4초 (11~12ms) | +5~+6초 (12ms) | +1~+4초 (11~12ms) | +4~+8초 (10~12ms) |
| Redis가 받은 명령 | `KEYS` 1, `DEL` 1 | `KEYS` 1, `DEL` 1 | `KEYS` 1, `UNLINK` 15,625 | `KEYS` 1, `UNLINK` 46,875 |

**1단계에서 새로 알게 된 것**
- **원문 경로(1-A)에서는 전체 삭제 한 번에 조회가 크게 두 번 멈췄다.** 100만 개에서 477ms와 1.17초, 300만 개에서 1.13초와 3.09초였다. 두 번째 멈춤이 풀린 때와 전체 삭제 응답이 온 때가 0.1초 안으로 거의 같았다.
- **멈춘 동안에는 응답이 하나도 오지 않았다.** 0.1초 표의 `끝남`이 0인 줄이 이어지다가, 풀리는 0.1초에 밀린 조회가 한꺼번에 끝났다(1-A 300만: 454건).
- **멈춘 구간의 `최대 응답` 막대는 처음이 가장 길고 0.1초마다 약 100ms씩 줄었다.** 멈춤이 풀리는 시각은 모두 같으니, 먼저 보낸 조회일수록 오래 기다린 것이다.
- **4.x 기본(1-B)은 전체 삭제가 23~40ms 만에 응답했지만, 그 직후 조회는 똑같이 멈췄다.** 100만 개에서 232ms, 300만 개에서 1.30초였다. 크게 멈춘 것은 한 번이었다.
- **키를 3배로 늘리니 가장 긴 멈춤도 길어졌다.** 1-A는 1.17초에서 3.09초, 1-B는 232ms에서 1.30초가 됐다.
- **큰 멈춤 말고 짧은 멈춤도 섞였다.** 1-A 300만의 두 큰 멈춤 사이(+1.48초, 362ms), 1-B 300만의 큰 멈춤 직후(+1.73초, 239ms), 삭제 10초 넘게 뒤(1-A 100만 +13.30초 238ms, 1-B 300만 +10.59초 103ms)에 나왔다. 1-A 300만의 사이 멈춤은 Claude 검증 실행 하나에서도 같은 자리(+1.58초, 361ms)에 나왔다.
- **삭제 뒤 캐시가 비어 1초 표 중앙값이 2ms에서 11~12ms로 올랐다.** 캐시에 없으면 가짜 DB(10ms)를 거치기 때문이다. 1-A는 삭제가 끝난 직후 1~2초 동안 올랐다. 1-B 300만은 +4~+8초로 늦게 오르고 길게 이어졌다.
- **같은 조건이어도 실행마다 시간이 꽤 달랐다.** 예를 들어 1-B 300만의 첫 멈춤은 직접 실행에서 1.30초, Claude 검증에서 636ms였다.

## 2단계: 원인 증명

1단계에서 본 멈춤을 **층마다 다른 증거로 하나씩 가른다.** 층은 셋이다: Redis, 앱과 Redis를 잇는 연결, 앱 JVM. 원문이 든 원인도 여기서 확인한다. 원문은 원인을 두 가지로 들었다.
- 싱글 스레드인 Redis에서 `KEYS`는 DB의 모든 키를 훑는 O(N) 명령이다.
- 키가 많으면 `DEL`도 Redis를 붙잡는다.

### 새 도구

| 파일 | 하는 일 |
|---|---|
| `scripts/evidence.py <이름> [products 키 수] [others 키 수]` | 1단계와 같은 조건(조회 초당 200건, 20초째에 전체 삭제 1번)으로 돌리면서 아래 증거를 함께 모아 같은 시간축에 놓는다. 시각은 전체 삭제를 보낸 때가 0이다. 결과는 `results/evidence-<이름>/`에 남는다 |

| 증거 | 어떻게 모으나 | 무엇을 가르나 |
|---|---|---|
| Redis 멈춤 | 수집기가 앱과 따로 Redis에 연결해 5ms마다 `CLIENT LIST`를 보낸다. 답이 50ms 넘게 늦은 구간이다 | Redis가 무언가에 붙잡혀 다른 명령을 처리하지 못한 때 |
| SLOWLOG | Redis가 10ms 넘게 실행한 명령, 걸린 시간, 그 명령이 온 연결 | Redis 멈춤이 어느 명령 때문인지 |
| 앱 연결 | 같은 `CLIENT LIST`로 본 앱의 Redis 연결. 0.1초마다 처리한 명령 수, 보낼 응답(Redis가 아직 다 보내지 못한 응답, `omem`), 받는 명령(Redis가 받고 있거나 받아 놓고 아직 끝내지 못한 명령, `qbuf` + `argv-mem`) | Redis는 한가한데 연결에 무엇이 걸려 있는지 |
| GC 멈춤 | 앱 GC 로그(`/tmp/gc.log`)의 멈춤(10ms 이상). 그동안 앱의 모든 스레드가 선다 | 앱 JVM이 통째로 선 때 |
| 스레드 덤프 | 전체 삭제가 시작된 것이 보이면 0.5초마다 12번, 앱의 관리 포트 actuator(`/actuator/threaddump`)에서 받는다. 전체 삭제를 부른 요청 스레드와 일하던 Lettuce I/O 스레드의 맨 위 프레임, 조회 요청 스레드가 무엇을 기다리는지 보여 준다. 2단계 직접 실행 때는 `kill -3`(SIGQUIT)으로 받았다. 바꾼 이유는 3단계에 적었다 | 그때 앱 안에서 누가 무엇을 하고 있었는지 |

- 조회 연결은 삭제 전에 명령이 가장 많이 오간 앱 연결이다(1단계 NOTE의 동기 공유 연결). 비동기면 나머지 앱 연결(반응형 공유 연결)을 삭제 연결로 따로 보여 준다.
- 바뀐 것: Redis 포트 6379를 열었다(수집기용). 앱이 GC 로그를 남긴다. 캐시 채우기에 다른 캐시를 채우는 옵션(`cache=others`)을 더했다.
- 앱, Redis, k6, 수집기가 한 컴퓨터(Docker Desktop VM 하나)를 나눠 쓴다. 그래서 SLOWLOG에도 GC에도 없는 0.1~0.35초짜리 Redis 멈춤이 가끔 보인다. Claude 검증에서는 삭제와 상관없는 시각(삭제 6초 전, 14초 뒤)에도 나왔다. 이런 멈춤은 이 실험의 원인으로 보지 않는다.

요약 읽는 법
- **조회가 멈췄다가 한꺼번에 풀린 때와 그동안의 증거:** 1단계와 같은 멈춤마다, 그 구간과 겹친 Redis 멈춤, GC 멈춤, 조회 연결의 큰 응답·명령(1MB 넘음)을 적는다.
- **SLOWLOG, 앱 GC 멈춤, 앱 스레드 덤프:** 시각과 함께 나열한다.
- **삭제 전후 0.1초 단위:** 위 증거를 0.1초 칸마다 나란히 놓는다. 같은 모양이 이어지는 줄은 접는다.

### 준비

```bash
./gradlew bootJar
```

```bash
CACHE_IMMEDIATE_WRITES=true docker compose up -d --build
```

### 실험 2-A: 원문 경로(동기)의 멈춤을 토막으로 나누기

```bash
python3 scripts/evidence.py 2a-sync-3m 3000000
```

**관찰 포인트**
- 첫 멈춤에서 Redis 멈춤은 얼마나 이어졌고, SLOWLOG의 어느 명령과 시간이 맞나?
- 첫 멈춤이 Redis 멈춤보다 길다면, 남은 동안 조회 연결의 "보낼 응답"은 몇 MB였나? 그때 스레드 덤프의 요청 스레드와 Lettuce I/O 스레드는 무엇을 하고 있었나?
- 두 큰 멈춤 사이에 조회는 정상이었나? 그동안 요청 스레드는 무엇을 하고 있었나?
- 마지막 큰 멈춤을 0.1초 표에서 토막으로 나눠 보자.
  - Redis 멈춤은 몇 초이고, SLOWLOG의 어느 명령과 맞나?
  - 그 앞에 Redis는 한가한데 조회 연결의 "명령"이 0인 구간이 있나? 그때 덤프의 Lettuce I/O 스레드는 무엇을 하고 있었나?
  - "받는 명령"이 커지던 구간은 언제인가?
- 짧은 멈춤들은 무엇과 겹치나?

### 실험 2-B: KEYS는 무엇을 훑나

products 캐시는 1,000개로 같게 두고, Redis에 다른 캐시의 키가 있을 때와 없을 때를 비교한다.

```bash
python3 scripts/evidence.py 2b-alone 1000
```

```bash
python3 scripts/evidence.py 2b-crowded 1000 3000000
```

**관찰 포인트**
- 두 실행의 전체 삭제 응답 시간과 SLOWLOG의 `KEYS` 시간은 어떻게 다른가? 지운 키 수는?
- 2b-crowded의 `KEYS` 시간을 2-A의 `KEYS` 시간과 비교하면?

### 실험 2-C: 4.x 기본(비동기)에서는

스위치 없이 앱을 다시 띄운다.

```bash
docker compose up -d app
```

```bash
python3 scripts/evidence.py 2c-async-3m 3000000
```

**관찰 포인트**
- 첫 멈춤의 길이는 Redis 멈춤, SLOWLOG의 `KEYS` 시간과 어떻게 맞나? 2-A의 첫 멈춤과 무엇이 다른가?
- `KEYS` 응답(약 70MB)은 어느 연결에 쌓였나? 그동안 조회 연결은?
- 삭제 연결에서 `UNLINK`가 오간 구간은 몇 초였나? 그동안 조회는 어땠나? 스레드 덤프의 Lettuce I/O 스레드는 무엇을 하고 있었나?
- 짧은 멈춤들은 무엇과 겹치나?

### 생각해 볼 질문 (2단계)

1. 2-B에서 지울 키는 1,000개뿐인데 `KEYS`가 오래 걸렸다면, `KEYS`의 시간은 무엇에 비례할까? 2-A의 `KEYS`가 2-B보다 더 걸렸다면 그 차이는 어디서 올까?
2. 동기 경로에서 Redis가 한가한데도 조회가 막히는 구간은 왜 생길까? Lettuce가 연결 하나를 모든 스레드가 같이 쓴다는 점과 어떻게 이어지나?
3. 운영에서는 같은 Redis를 앱 서버 여러 대가 쓴다. 전체 삭제를 부르지 않은 다른 서버의 조회는 2-A의 어느 토막에서 멈출까? 2-C에서는?
4. GC 멈춤이 전체 삭제 무렵에 몰렸다면 왜일까? 앱은 키 300만 개를 어떤 모양으로 들고 있었나?
5. 원문은 `KEYS` 대신 `SCAN`을 쓰게 바꿨다. 그러면 2-A의 어느 토막이 줄고 어느 토막이 남을까? (3단계에서 본다)

### 2단계 결과

직접 실행(2-A는 2026-10-13 17:27, 2-B·2-C는 2026-10-14 11:23~11:29)한 값이다. 네 번 모두 `주의` 없이 끝났다. Claude가 검증하며 돌린 값은 `results/claude-verification/stage2/`에 있고 같은 모양이었다.

| 관찰 항목 | 2-A 동기 300만 | 2-B 1,000개만 | 2-B + 다른 키 300만 | 2-C 비동기 300만 |
|---|---|---|---|---|
| 전체 삭제 응답 | 6.15초 | 33ms | 329ms | 36ms |
| SLOWLOG (명령, 시간, 연결) | `KEYS` 1.03초, `DEL` 키 300만 개 2.11초. 둘 다 조회 연결 | 없음 | `KEYS` 311ms(조회 연결). `DEL` 키 1,000개는 10ms 안이라 없음 | `KEYS` 926ms(삭제 연결). 키 64개짜리 `UNLINK` 5번이 11~26ms |
| 큰 멈춤과 그동안의 Redis 멈춤 | +0.04~+1.49초(최대 1.42초) 중 Redis 1.03초<br>+2.69~+6.54초(3.60초) 중 Redis 2.21초 | 없음 | +0.00~+0.32초(313ms) 중 Redis 308ms | +0.03~+0.98초(938ms) 중 Redis 926ms |
| Redis는 한가한데 조회가 막힌 구간과 그때의 증거 | +1.07~+1.38초: 조회 연결 보낼 응답 67.6MB, I/O 스레드 `RedisStateMachine.decode`<br>+2.7~+3.9초: 조회 연결 명령 0, 이어서 받는 명령 8.9 → 45.4MB, I/O 스레드 `CommandArgs.encode` | 없음 | 없음 | 없음. `KEYS` 응답 67.7MB는 삭제 연결로 나갔고(+0.9~+1.8초) 그동안 조회 연결은 정상 |
| 짧은 멈춤과 겹친 증거 | +2.01초: GC 422ms | 없음 | 없음 | +1.19초 GC 138ms, +1.50초 GC 105ms, +6.41초 GC 103ms<br>+1.82초: Redis 165ms. 느린 `UNLINK` 5개가 같은 초에 끝남<br>+3.32초: 조회 1건 112ms(증거 없음) |

- 2-C의 `UNLINK`는 +2.2~+6.9초에 삭제 연결로 나뉘어 오갔다(명령 46,974개).
- 2-C에서는 수집기가 삭제 0.92초 전에 52ms짜리 Redis 응답을 한 번 봐서 스레드 덤프가 1초쯤 일찍 시작됐다(-0.60초부터).
- **(3단계에서 알게 됨) 2단계 실행은 덤프 때문에 시간이 늘어났을 수 있다.** 2단계는 스레드 덤프를 `kill -3`으로 떴다. 3단계에서 같은 `SCAN` 전체 삭제를 재 보니, 덤프 없이 5.0~6.2초 걸리던 것이 `kill -3` 덤프 12번과 함께 10.4초가 걸렸다. 앱이 덤프를 표준 출력에 찍는 동안 모든 스레드가 서고, 덤프 하나가 1.2MB라 Docker 로그로 넘기는 일도 무겁다. 그래서 2-A의 `DEL`(2.11초)처럼 덤프가 뜨던 동안의 시간은 덤프 없이 잰 1-A(1,713ms)보다 길게 나왔을 수 있다. 덤프는 대개 Redis가 처음 멈춘 뒤(`KEYS`가 끝난 뒤)에 시작해서 `KEYS` 시간에는 영향이 적다. 다만 2-C는 덤프가 삭제 전에 시작했다. 멈춤이 어느 층에서 생겼는지 가른 결론은 그대로다.

**2단계에서 새로 알게 된 것**
- **원문이 든 원인이 맞았다.** 동기 경로에서 Redis가 멈춘 것은 `KEYS`(1.03초)와 `DEL`(2.11초)을 실행하는 동안이었다. Redis가 멈춘 구간과 SLOWLOG의 실행 시간이 맞았다.
- **`KEYS`는 DB의 모든 키를 훑는다(2-B).** products 키가 1,000개뿐일 때는 `KEYS`가 10ms 안에 끝났다. 같은 1,000개에 다른 캐시 키 300만 개가 함께 있으면 311ms가 걸렸고, 조회도 그만큼 멈췄다. 지운 키는 둘 다 1,000개였다.
- **`KEYS`의 시간은 훑는 키와 찾은 키 둘 다에 달렸다.** 300만 개를 훑어 300만 개를 찾은 2-A는 1.03초, 300만 개를 훑어 1,000개를 찾은 2-B는 311ms였다(Claude 검증 717ms·326ms). 찾은 키가 많으면 응답(70MB)을 만드는 데 시간이 더 든다.
- **동기 경로에서는 조회가 Redis보다 오래 멈췄다.** 2-A에서 Redis가 멈춘 시간은 합쳐 약 3.2초인데, 조회가 멈춘 구간은 합쳐 약 5.8초였다. 차이는 둘에서 왔다.
  - 같은 연결의 줄: 70MB 응답이 넘어오는 0.3초, `DEL` 명령을 만들어 쓰고 보내는 1.3초. 이 구간에 Redis는 한가했다. 조회 연결에 큰 응답이나 명령이 걸려 있었고, 덤프의 I/O 스레드는 그것을 해석하거나 쓰고 있었다. 앱의 모든 조회가 Redis 연결 하나와 그 연결의 Lettuce I/O 스레드 하나를 같이 써서 생긴 일이다.
  - GC: 422ms 등.
- **비동기(2-C)는 조회 멈춤(938ms)이 `KEYS` 실행(926ms)과 거의 같았다.** `KEYS` 응답과 `UNLINK`가 조회와 다른 연결(반응형 연결)로 오가서 같은 연결의 줄이 생기지 않았다.
- **짧은 멈춤은 대부분 앱 GC였다.** 2-A의 GC 422ms는 `401M->375M`로 거의 줄지 않아 살아 있는 객체가 많았다. 그때 앱은 키 300만 개를 Set(동기, 덤프 `HashMap.putVal`)이나 `ByteBuffer` 목록(비동기, 덤프 `KeyListOutput.set`)으로 힙에 들고 있었다.
- **동기에서는 Tomcat 요청 스레드 200개가 모두 Redis 응답을 기다리며 묶였다.** +1.39초 덤프와 +3.78~+5.71초 덤프에서 200개 중 199개가 `doGet`에서 기다렸고, 나머지 하나는 전체 삭제 요청 스레드였다.

## 3단계: 해결책 재현

원문의 해결책은 전체 삭제할 키를 `KEYS` 대신 `SCAN`으로 찾게 바꾸는 것이다. `RedisCacheManagerBuilderCustomizer`로 캐시 쓰기 도구의 배치 전략을 `BatchStrategies.scan(n)`으로 바꿨다. 원문은 이 해결책의 한계 두 가지와 실무 조언 두 가지를 함께 적었다.
- 한계 ①: `SCAN`도 결국 모든 키를 훑는다. 원문에서는 캐시가 많아 `SCAN` 호출이 무수히 많았고 API가 타임아웃(60초)났다.
- 한계 ②: 잠금을 쓰는 캐시 쓰기 도구(`lockingRedisCacheWriter`)면 `SCAN`이어도 지우는 동안 막힌다.
- 조언 ①: 운영 Redis는 `KEYS`를 막아 두는 경우가 많다(`rename-command KEYS ""`). 그러면 기본 전략에서 `RedisCommandExecutionException`이 난다.
- 조언 ②: 키가 많으면 `DEL` 대신, 메모리 해제를 백그라운드로 미루는 `UNLINK`가 낫다(`lazyfree-lazy-user-del`).

이 단계에서는 이것들을 2-A와 같은 조건(원문처럼 동기, 키 300만 개, 조회 초당 200건)에서 차례로 확인한다. 원문의 코드는 이미지라 `SCAN` 한 번에 몇 개씩(n) 찾았는지 알 수 없다. 여기서는 1,000개로 하고(3-A), 100개로 줄였을 때(3-B)도 본다.

### 바뀐 것

- 스위치 다섯 개를 더했다(실험 환경의 스위치 표).
  - 4.x에서 동기 쓰기와 함께 고르려고 `RedisCacheWriter.create(...)`로 조합한다(`CacheWriterConfig`).
  - 원문(3.3.7)은 `RedisCacheWriter.nonLockingRedisCacheWriter(factory, BatchStrategies.scan(n))`처럼 팩토리 메서드로 바꿨다. 이 메서드도 4.1.1에 남아 있다.
- `evidence.py`
  - 리포트 머리에 켜진 스위치를 적고, Redis가 받은 명령마다 횟수와 실행 시간 합(`INFO commandstats`)을 적는다.
  - 결과가 섞였는지 보는 검사를 `SCAN`·잠금에 맞게 고쳤다. `SCAN`이면 `KEYS`가 0번이어야 하고, 동기면 `DEL`, 비동기면 `UNLINK`로 지운다.
  - 스레드 덤프를 actuator(`/actuator/threaddump`)로 받는다. 2단계의 `kill -3`은 실험 자체를 크게 느리게 했다(아래 표). 앱이 덤프를 표준 출력에 찍는 동안 모든 스레드가 서고, Docker 로그로 넘기는 일도 무거워서다. 덤프를 끄려면 `DUMPS=0`을 앞에 붙인다.
  - 덤프 요약에서 조회 요청 스레드가 무엇을 기다리는지(Redis 응답, 잠금, 쉼) 센다.
  - `SCAN`으로 지우면 같은 모양이 오래 이어져서 0.1초 표는 앞 3초만 보인다.
- `evict_once.py`(3-D): 부하 없이 전체 삭제를 한 번 부르고, 응답과 캐시가 실제로 비었는지, 앱 로그의 오류를 보여 준다.
- `big_key_del.sh`(3-E): 값이 큰 키 하나를 `DEL`로 지울 때 `lazyfree-lazy-user-del` 설정에 따라 무엇이 다른지 본다.

**측정 도구도 실험을 흔든다.** 같은 `SCAN` 전체 삭제(1,000개씩, 키 300만 개)를 재는 방법만 바꿔 돌린 값이다(Claude 검증).

| 측정 | 전체 삭제 응답 | `SCAN` 한 번 평균 | `DEL` 한 번 평균 |
|---|---|---|---|
| 1단계 실행기(수집기·덤프 없음) | 6.24초 | 522µs | 847µs |
| 수집기만 | 5.02초 | 420µs | 661µs |
| 수집기 + actuator 덤프 12번 | 7.53초 | 581µs | 985µs |
| 수집기 + `kill -3` 덤프 12번(2단계 방식) | 10.38초 | 1,033µs | 1,194µs |

그래서 걸린 시간을 비교하는 3-A, 3-B, 3-E는 덤프를 끄고(`DUMPS=0`) 돌린다. 스레드가 무엇을 기다리는지 봐야 하는 3-C만 덤프를 뜬다. 비교 기준은 덤프 없이 잰 1-A 300만(1단계 직접 실행)이다.

덤프를 꺼도 가끔 Redis가 수백 ms 멈춘다. 그때 SLOWLOG에는 키 1,000개짜리 `DEL` 하나가 279ms처럼, 명령이 할 일로는 설명되지 않게 오래 걸린 기록이 남는다(Claude 검증 3-A). 같은 조건이어도 실행마다 시간이 꽤 다르다(덤프 없는 3-A가 5.0초, 6.2초, 9.6초). 2단계의 원인 모를 멈춤과 같은 종류로, Redis 프로세스가 그 순간 CPU나 메모리를 제때 받지 못한 것으로 보인다. 이런 멈춤은 해결책의 효과로 보지 않는다.

### 준비

```bash
./gradlew bootJar
```

### 실험 3-A: 원문의 해결책, SCAN으로 찾기

```bash
CACHE_IMMEDIATE_WRITES=true CACHE_BATCH_STRATEGY=scan docker compose up -d --build
```

```bash
DUMPS=0 python3 scripts/evidence.py 3a-scan-1000 3000000
```

**관찰 포인트**
- 1-A 300만(같은 조건에서 `KEYS`)과 비교해, 조회가 멈췄다가 풀린 때는 어떻게 달라졌나? Redis 멈춤은?
- Redis가 받은 `SCAN`과 `DEL`은 몇 번인가? 키 300만 개를 어떻게 나눠 지웠나?
- 전체 삭제 응답 시간과, Redis가 `SCAN`·`DEL`을 실행한 시간 합을 비교하면?

### 실험 3-B: 한계 ①, 오래 걸린다

`SCAN` 한 번에 100개씩 찾게 줄인다.

```bash
CACHE_IMMEDIATE_WRITES=true CACHE_BATCH_STRATEGY=scan CACHE_SCAN_BATCH_SIZE=100 docker compose up -d app
```

```bash
DUMPS=0 python3 scripts/evidence.py 3b-scan-100 3000000
```

**관찰 포인트**
- 전체 삭제 응답은 3-A의 몇 배인가? `SCAN`·`DEL` 횟수는?
- 그중 Redis가 명령을 실행한 시간(실행 합)은 얼마인가? 나머지는 어디서 왔을까?

### 실험 3-C: 한계 ②, 잠금을 쓰는 캐시 쓰기 도구

`SCAN`(1,000개씩)은 그대로 두고 잠금을 켠다. 이번에는 덤프를 뜬다.

```bash
CACHE_IMMEDIATE_WRITES=true CACHE_BATCH_STRATEGY=scan CACHE_LOCKING=true docker compose up -d app
```

```bash
python3 scripts/evidence.py 3c-locking 3000000
```

조회가 오래 막히면 k6가 조회 일부를 제때 보내지 못할 수 있다. 그때는 리포트에 `참고`로 적힌다. 다시 돌릴 일은 아니다.

**관찰 포인트**
- 조회가 멈춘 구간은 전체 삭제의 어디서부터 어디까지인가? 그동안 Redis는 멈췄나?
- 스레드 덤프에서 조회 요청 스레드는 무엇을 기다리나?
- Redis가 받은 잠금 확인(`EXISTS`)은 몇 번인가? 누가, 왜 보냈을까?

### 실험 3-D: 원문의 조언 ①, KEYS를 막아 둔 Redis

Redis가 `KEYS`를 막은 채(`REDIS_KEYS_COMMAND=`) 세 경우를 차례로 돌린다. 경우마다 키 1,000개를 채우고 전체 삭제를 한 번 부른다.

원문처럼 동기, `KEYS`로 찾기:

```bash
CACHE_IMMEDIATE_WRITES=true REDIS_KEYS_COMMAND= docker compose up -d
```

```bash
python3 scripts/evict_once.py 3d-sync-keys
```

4.x 기본(비동기), `KEYS`로 찾기:

```bash
REDIS_KEYS_COMMAND= docker compose up -d
```

```bash
python3 scripts/evict_once.py 3d-async-keys
```

원문처럼 동기, `SCAN`으로 찾기:

```bash
CACHE_IMMEDIATE_WRITES=true CACHE_BATCH_STRATEGY=scan REDIS_KEYS_COMMAND= docker compose up -d
```

```bash
python3 scripts/evict_once.py 3d-sync-scan
```

**관찰 포인트**
- 세 경우의 전체 삭제 응답과, 캐시가 실제로 비었는지, 앱 로그의 오류는?
- 4.x 기본 경로에서는 무엇이 다른가? 운영이라면 언제 알아챌 수 있을까?

### 실험 3-E: 원문의 조언 ②, DEL 대신 UNLINK

Redis가 `DEL`도 `UNLINK`처럼 다루게 하고(`REDIS_LAZYFREE_USER_DEL=yes`), 원문 경로(동기, `KEYS`)로 키 300만 개를 지운다.

```bash
CACHE_IMMEDIATE_WRITES=true REDIS_LAZYFREE_USER_DEL=yes docker compose up -d
```

```bash
DUMPS=0 python3 scripts/evidence.py 3e-lazyfree 3000000
```

값이 큰 키 하나(필드 100만 개짜리 해시)를 지울 때와 비교한다.

```bash
./scripts/big_key_del.sh
```

끝나면 스위치를 모두 기본값으로 돌린다.

```bash
docker compose up -d
```

**관찰 포인트**
- SLOWLOG의 `DEL` 시간과 Redis 멈춤을 1-A 300만(`lazyfree-lazy-user-del no`)과 비교하면?
- 리포트의 "백그라운드로 넘겨 해제한 객체"는 몇 개인가?
- 값이 큰 키 하나를 지울 때는 어떻게 다른가?

### 생각해 볼 질문 (3단계)

1. `SCAN`으로 바꾸면 Redis가 오래 멈추지 않는 이유는? 대신 무엇이 늘었나?
2. 3-B에서 전체 삭제 시간의 대부분이 Redis 실행이 아니었다면, 원문처럼 앱과 Redis가 다른 서버일 때는 어떻게 될까? 원문의 API 타임아웃(60초)과 이어 보자.
3. 잠금을 쓰는 캐시 쓰기 도구는 무엇을 막으려고 있을까? 그 대가는?
4. `UNLINK`(lazyfree)가 효과를 보는 것은 어떤 키를 지울 때인가? 이 실험의 키는 어떤 키인가?
5. 원문은 결론으로 `allEntries = true`를 쓰지 말라고 했다. 캐시를 통째로 비워야 할 때, Redis를 붙잡지 않는 다른 방법은 무엇이 있을까?

### 3단계 결과

직접 실행(2026-10-14. 3-A 15:22, 3-B 16:17, 3-C 22:30, 3-D 22:44~22:50, 3-E 22:54)한 값이다. 모두 `주의` 없이 끝났다(3-C는 `참고` 하나). Claude가 검증하며 돌린 값은 `results/claude-verification/stage3/`에 있다.

| 관찰 항목 | 3-A SCAN 1,000개씩 | 3-B SCAN 100개씩 | 3-C 잠금 | 3-E DEL을 UNLINK처럼 |
|---|---|---|---|---|
| 전체 삭제 응답 | 7.02초 | 16.31초 | 9.81초 | 10.21초 |
| Redis가 받은 명령 (횟수, 실행 합) | `SCAN` 2,996번(1.90초)<br>`DEL` 3,001번(2.74초) | `SCAN` 29,605번(2.57초)<br>`DEL` 30,000번(3.47초) | `SCAN` 2,996번(2.30초)<br>`DEL` 3,001번(3.52초)<br>`EXISTS` 39,368번(386ms) | `KEYS` 1번(1.11초)<br>`DEL` 1번(4.16초) |
| 조회가 멈췄다가 풀린 때 (가장 긴 멈춤) | +2.96~+3.07초 (106ms). 100ms 넘게 기다린 조회는 1건 | 없음 | +0.04~+10.27초 (9.88초). 전체 삭제 내내 | +0.05~+1.52초 (1.43초)<br>+3.58~+10.72초 (6.73초)<br>그 사이 GC·Redis로 짧게 3번(최대 253ms) |
| Redis 멈춤 | 없음(수집기 답 최대 49ms) | +0.14초 73ms, +15.03초 50ms | +3.44초 85ms | +0.06~+1.17초(1.12초)<br>+5.84~+10.18초(4.34초)<br>그 밖 194ms, 63ms |
| 백그라운드로 넘겨 해제한 객체 | - | - | - | 0개 |

| 관찰 항목 | 3-D 동기 + KEYS | 3-D 4.x 기본 + KEYS | 3-D 동기 + SCAN |
|---|---|---|---|
| 전체 삭제 응답 | HTTP 500 (151ms) | HTTP 200 (16ms) | HTTP 200 (22ms) |
| 캐시 키 (삭제 전 → 2초 뒤) | 1,000 → 1,000 | 1,000 → 1,000 | 1,000 → 0 |
| 앱 로그의 오류 | `RedisCommandExecutionException: ERR unknown command 'KEYS', with args beginning with: 'products::*'` | 없음 | 없음 |

- 값이 큰 키 하나(`big_key_del.sh`, Claude 검증 값. 직접 실행 출력은 파일로 남지 않았다): `lazyfree-lazy-user-del no`면 필드 100만 개 해시 하나의 `DEL` 응답까지 53ms(백그라운드 0개), `yes`면 1ms(백그라운드 1개).
- 3-C에서 덤프 12번 중 첫 번째(+0.85초)는 조회 요청 스레드 121개, 나머지 11번은 199개가 모두 잠금 대기였다. 조회가 오래 막혀 k6가 조회 233건을 제때 보내지 못했다(`참고`).
- `SCAN`으로 지운 실행(3-A·3-C, Claude 검증 포함)은 삭제를 시작한 직후에 Redis 답이 10~80ms로 느려지곤 했다. SLOWLOG에도 할 일보다 훨씬 오래 걸린 `SCAN`·`DEL`(10~38ms)이 몰렸다. 원인은 확인하지 않았다.
- 3-E는 Redis 설정과 상관없는 앱 쪽 일(키 300만 개를 받아 `DEL` 명령을 만들기, +1.44~+5.47초)도 2-A의 두 배 가까이 걸렸다. 실행 전체가 느렸던 것으로 보고, `DEL` 4.16초를 lazyfree 탓으로 보지 않는다. Claude 검증의 3-E는 `DEL` 2.12초로, lazyfree를 끈 2-A(2.11초)와 같았다.

**3단계에서 새로 알게 된 것**
- **원문의 해결책대로 `SCAN`으로 찾으니 Redis가 멈추지 않았다(3-A).** 같은 조건에서 `KEYS`로 지운 1-A 300만은 조회 909건이 100ms 넘게 기다렸고 가장 긴 멈춤이 3.09초였다. 3-A는 100ms 넘게 기다린 조회가 1건(106ms)이었고, Redis가 50ms 넘게 답하지 못한 때가 없었다. 가장 오래 걸린 명령도 `DEL` 31ms였다. 조회 연결에 큰 응답이나 명령도 걸리지 않았다. `SCAN` 응답과 `DEL` 명령이 하나에 약 23.6KB였다.
- **대신 전체 삭제는 길어지고 명령이 많아졌다.** 3-A는 7.02초(1-A 5.09초)에 명령 약 6,000개(1-A는 2개)였다. Redis 실행 합도 4.64초로 1-A(`KEYS` 876ms + `DEL` 1,713ms)보다 길었다.
- **`SCAN`을 100개씩으로 줄이니(3-B) 전체 삭제가 16.31초가 됐다.** 명령은 59,605개로 3-A의 10배였다. Redis가 명령을 실행한 시간은 6.04초뿐이고, 나머지 10.3초(63%)는 명령을 주고받고 앱이 처리하는 데 쓰였다. 조회는 한 번도 100ms 넘게 기다리지 않았다.
- **잠금을 켜면(3-C) `SCAN`이어도 조회가 전체 삭제 내내 막혔다.** +0.04~+10.27초 동안 조회 1,792건이 100ms 넘게 기다렸고 가장 긴 것은 9.88초였다. 그동안 Redis는 거의 멈추지 않았다(85ms 한 번). 조회 요청 스레드가 모두 잠금 키(`products~lock`)가 사라지기를 기다렸다. 50ms마다 잠금 키를 확인해서 `EXISTS`가 39,368번 왔다. 스레드 200개가 9.8초 동안 50ms마다 확인한 수(약 39,200)와 맞는다. 멈추는 곳이 Redis에서 앱의 요청 스레드로 옮겨 갔다.
- **`KEYS`를 막은 Redis(3-D)에서 원문 경로(동기)는 원문대로 `RedisCommandExecutionException`이 났다.** 응답은 500이었고 캐시는 그대로였다.
- **원문과 다른 점: 4.x 기본(비동기)은 같은 상황에서 조용히 실패했다.** 응답은 200이었고 앱 로그에 오류가 없었지만 캐시는 지워지지 않았다. Redis는 똑같이 거절했다. 다만 Spring Data Redis가 비동기 삭제의 결과(`CompletableFuture`)를 받아 보지 않고 버려서 오류가 사라졌다. `SCAN`으로 찾는 동기 경로는 제대로 지웠다.
- **원문과 다른 점: `DEL`을 `UNLINK`처럼 처리하게 해도(3-E) 키 300만 개는 메인 스레드가 지웠다.** 백그라운드로 넘겨 해제한 객체가 0개였고, `DEL`이 Redis를 4.16초 붙잡았다. 원문은 키가 많으면 `UNLINK`가 낫다고 했지만, Redis는 값마다 해제할 일의 양을 어림해 원소가 많은 컬렉션(필드가 많아 해시테이블로 저장된 해시 등)만 백그라운드로 넘긴다. 문자열은 50MB여도 그 자리에서 해제한다(Claude 확인). 이 실험의 값은 약 105바이트짜리 문자열이다. 값이 큰 키 하나(해시 필드 100만 개)는 `UNLINK`처럼 처리하면 백그라운드로 넘어가 `DEL` 응답이 53ms에서 1ms로 줄었다(Claude 검증). 1-B·2-C의 비동기 경로가 `UNLINK`로 Redis를 오래 붙잡지 않은 것도 lazyfree 덕이 아니라 64개씩 나눠 지웠기 때문으로 보인다.
- **같은 조건이어도 실행마다 시간이 꽤 달랐다.** 직접 실행과 Claude 검증이 3-A 7.02초와 5.02~9.57초, 3-B 16.31초와 26.38초, 3-C 9.81초와 12.61초, 3-E 10.21초와 6.12초였다. 그래서 해결책끼리는 걸린 시간보다 조회가 막혔는지, Redis가 멈췄는지로 비교했다.
