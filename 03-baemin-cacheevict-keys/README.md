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
| 1. 재현 | 캐시 조회 부하 중에 전체 삭제를 부르면 어떻게 되나 | |
| 2. 원인 증명 | | |
| 3. 해결책 재현 | 원문의 `SCAN` 전환과 그 한계 | |
| 4. 원문 너머 | 필요하면 정한다 | |

## 실험 환경

```
GET /products/{id}              상품 조회. @Cacheable("products")라 캐시에 없을 때만 가짜 DB(10ms)에서 읽는다
POST /experiments/seed?count=N  실험용: products 캐시를 N개로 채운다(@Cacheable과 같은 키·값 형식)
POST /experiments/evict-all     원문의 @CacheEvict(cacheNames = "products", allEntries = true)
 │
 ▼
app 컨테이너 (Spring Boot, Lettuce) ─▶ Redis
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
