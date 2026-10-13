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
| 2. 원인 증명 | | |
| 3. 해결책 재현 | 원문의 `SCAN` 전환과 그 한계 | |
| 4. 원문 너머 | 필요하면 정한다 | |

## 실험 환경

```
k6 ─ 상품 조회 초당 200건 + 전체 삭제 1번 (1단계부터)
 │
 ▼
GET /products/{id}              상품 조회. @Cacheable("products")라 캐시에 없을 때만 가짜 DB(10ms)에서 읽는다
POST /experiments/seed?count=N  실험용: products 캐시를 N개로 채운다(@Cacheable과 같은 키·값 형식)
POST /experiments/evict-all     원문의 @CacheEvict(cacheNames = "products", allEntries = true)
 │
 ▼
app 컨테이너 (Spring Boot, Lettuce) ─▶ Redis (RDB 스냅샷 끔)
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
