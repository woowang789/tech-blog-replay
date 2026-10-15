# 04. 올리브영 「올영세일 선착순 쿠폰, 미발급 0%를 향한 여정」 재현

> 원문: [올영세일 선착순 쿠폰, 미발급 0%를 향한 여정 — Redis와 Message Queue로 구축한 비동기 시스템의 정합성 개선기](https://oliveyoung.tech/2025-12-15/fcfs-coupon/) (올리브영 테크블로그, 2025-12-15)

## 원문 요약

- **구조:** 선착순 쿠폰 발급은 MQ 기반 비동기다. 온라인몰(앞단)이 Redis에서 발급 수량을 읽어 1차 유효성 검사를 하고, 통과하면 Message Queue에 메시지를 발행한 뒤 사용자에게 "발급 성공"으로 응답한다. 발급 워커가 메시지를 받아 2차 유효성 검사를 하고 쿠폰을 최종 발급한다(DB). 수량은 DB 대신 Redis에 쿠폰별 키로 두고 쿠폰 유효 기간만큼 TTL을 건다.
- **장애:** 2025년 6월 올영세일(7일) 동안 워커의 2차 검사가 실패해 쿠폰이 발급되지 않은 건이 생겼다. 사용자는 이미 "발급 성공" 응답을 받았으니 CS 문의로 이어졌다. 평균 미발급률 약 0.014%(10,000건당 1.4건), 일차별 0.004~0.037%.
- **원인 세 가지:**
  1. **Time Gap:** 1차 검증(T0)과 워커의 재검증(T3) 사이에 MQ 발행·수신 지연이 있다. 그 사이 수백 건이 몰리면 1차를 통과한 요청이 2차에서 떨어진다.
  2. **이중 검증 오버헤드:** 워커의 재검증은 필요하지만, Time Gap 때문에 앞단의 1차 검증이 무의미해진다.
  3. **Redis GET/INCR 원자성 부재:** 수량을 읽는 `GET`과 올리는 `INCR`이 별도 명령이라 그 사이에 다른 요청이 끼어든다. 수량 오버플로우(과발급)가 난다.
- **개선 시도:**
  1. **발급 수량 선차감:** `INCR`을 워커가 아닌 앞단에서 한다(Time Gap 줄이기). 워커의 DB 처리가 실패하면 되돌린다. 미발급이 줄었지만 남았다. `GET`과 `INCR`이 떨어져 있는 한 경합이 막히지 않아서다.
  2. **Lua 스크립트:** `GET`·비교·`INCR`을 스크립트 하나로 묶어 원자적으로 실행한다. 미발급·과발급 0건이 됐지만 성능이 약 21% 떨어져 기각했다(Redis가 싱글 스레드라 스크립트가 도는 동안 다른 요청이 기다린다. 디버깅·모니터링도 어렵다).
  3. **이중 카운터:** 요청 수량 키(`coupon:{id}:countReq`)를 먼저 올려 동시 요청을 걸러 내고, 통과한 요청만 실제 발급 수량 키(`coupon:{id}:count`)를 올린다. Lua 없이 명령 2개로 해결하며 성능 저하는 약 8%였다. 워커로 넘어가는 초과 발급은 0건.
- **최종:** 1번 + 3번. 개발 환경 부하 테스트(제한 10,000건)에서 발급 성공 응답 10,162건 → 10,000건, 미발급 162건(1.62%) → 0건. 9월 올영세일에서 기능 플래그를 4일차부터 켜니 미발급 0건, 처리량 저하 없음.
- **운영 고려:** 키 네이밍과 TTL(쿠폰 종료 + 1시간), `count`와 `countReq`의 차이 모니터링과 알람, Redis 장애 시 DB fallback, 두 수량이 어긋나면 정합성 보정.
- **원문 환경:** Kotlin + `RedisTemplate`, Message Queue는 RabbitMQ(원문이 링크한 "쿠폰 발급 RabbitMQ 도입기"), DB. 버전은 밝히지 않았다. 원문의 그림(발급 흐름, 수량 차감 흐름도)은 이미지라 글에 적힌 설명으로 구조를 세웠다.

## 장애 연쇄

```
세일이 열리고 발급 요청이 ms 단위로 몰린다
  ▼ 온라인몰: Redis GET으로 수량을 읽어 1차 검증. 아직 남았다 → MQ에 발행하고 사용자에게 "발급 성공" 응답
  ▼ 같은 순간 들어온 다른 요청들도 같은 수량을 보고 통과한다 (수량을 올리는 INCR은 워커의 일이라 아무도 올리지 않았다)
  ▼ 워커가 메시지를 받을 때는 앞서 받은 요청들이 수량을 다 썼다 (Time Gap) → 2차 검증 실패 → 미발급
  ▼ 워커끼리도 GET과 INCR이 떨어져 있어 경합한다 → 제한을 넘겨 발급 (과발급)
  ▼ "발급 성공"을 본 고객에게 쿠폰이 없다 → CS 문의
```

## 진행 단계

| 단계 | 내용 | 상태 |
|---|---|---|
| 0. 사전 확인 | 최신 버전(Spring Boot 4.1.1, Spring Data Redis 4.1.1, Spring AMQP 4.1.1, RabbitMQ 4.3.6, Redis 8.10.2)에서도 원문의 기존 구조가 그대로 만들어지고(`get()`·`increment()`는 `GET`·`INCR` 두 명령), 동시 요청에서 미발급·과발급이 생기는가 | ✅ 완료 |
| 1. 재현 | 원문의 부하 테스트처럼 제한 10,000건에 그보다 많은 요청을 한꺼번에 보내 발급 성공 응답 수, 미발급 건수·미발급률, 과발급을 잰다. 원문 수치(10,162건, 미발급 162건, 1.62%)와 비교한다 | |
| 2. 원인 증명 | 원문이 든 세 원인을 하나씩 증거로 가른다. Time Gap(1차 검증부터 워커 재검증까지의 시간과 그동안 통과한 요청 수), 이중 검증(1차를 통과했는데 2차에서 떨어진 건), GET/INCR 원자성 부재(워커끼리의 경합으로 제한을 넘기는 과발급) | |
| 3. 해결책 재현 | 원문의 세 시도를 같은 부하 조건에서 차례로. 선차감(미발급이 줄지만 남는가), Lua 스크립트(0건이 되는가, 성능 저하 21%), 이중 카운터 + 선차감(0건, 성능 저하 8%) | |
| 4. 원문 너머 | 필요하면 정한다 | |

## 실험 환경

```
k6 ─ 서로 다른 사용자가 같은 쿠폰의 발급을 한꺼번에 요청 (0단계부터)
 │
 ▼
POST /coupons/{couponId}/issue?userId=N        온라인몰(앞단). Redis GET으로 1차 검증 → 통과하면 MQ에 발행하고 200 SUCCESS, 마감이면 409 SOLD_OUT
POST /experiments/reset?couponId=C001&limit=N  실험용: 큐·DB·Redis 수량·집계를 모두 비우고 제한 수량이 N인 쿠폰을 만든다
GET  /experiments/summary?couponId=C001        실험용: 성공 응답 수, 실제 발급 수, 미발급 수, 과발급 수, 큐 잔량, Time Gap
 │
 ▼
app 컨테이너 (Spring Boot)
 IssueService(앞단) ─ GET coupon:C001:count ─▶ RabbitMQ 큐 coupon-issue ─▶ IssueWorker (소비자 4개)
                                                                              ├ GET coupon:C001:count  2차 검증. 마감이면 issue_failures에 기록 (= 미발급)
                                                                              └ INCR coupon:C001:count → MySQL coupon_issues에 저장 (= 발급)
```

- Redis 키는 원문의 이름(`coupon:{couponId}:count`)을 쓰고, 처음 만들 때 쿠폰 종료 시각까지의 TTL을 건다.
- 발급 워커는 원문에서 별도 인스턴스지만 여기서는 같은 앱 안의 리스너 소비자 스레드로 둔다. 소비자 수가 "워커 몇 대가 동시에 처리하는가"다.
- 원문의 유저별 키(1인 1매 확인)는 넣지 않았다. k6가 사용자마다 한 번씩만 요청한다.
- 집계의 뜻: `successResponses`(발급 성공 응답) = `issued`(실제 발급, DB) + `unissued`(워커 2차 검증 실패, DB). `overIssued` = `issued` − 제한 수량. `queued`가 0이어야 워커가 다 처리한 뒤의 집계다.

| 구성 요소 | 버전 |
|---|---|
| Spring Boot | 4.1.1 |
| Spring Framework | 7.0.9 |
| Spring Data Redis / Lettuce | 4.1.1 / 7.5.2 |
| Spring AMQP (spring-rabbit) / amqp-client | 4.1.1 / 5.31.0 |
| RabbitMQ | 4.3.6 (management 포함) |
| Redis | 8.10.2 |
| Hibernate / HikariCP | 7.4.5.Final / 7.0.2 |
| MySQL | 8.4.11 (Connector/J 9.7.0) |
| Java | 21 (Eclipse Temurin) |
| k6 | 2.2.0 (부하 도구, 로컬에 설치) |

| 스위치 | 뜻 |
|---|---|
| `WORKER_CONCURRENCY` | 발급 워커가 동시에 처리하는 메시지 수(리스너 소비자 스레드 수). 기본 4 |

스위치는 `docker compose up -d` 앞에 붙여 준다. 붙이지 않은 스위치는 기본값으로 돌아간다.

## 0단계: 사전 확인 결과

- **원문의 코드 패턴이 최신 버전에서도 그대로다.** Spring Data Redis 4.1.1의 `opsForValue().get()`은 `GET`, `increment()`는 `INCR` 한 번씩이고 둘을 묶어 주는 것은 없다. 초기화 뒤 발급 요청 1건을 보내며 `redis-cli MONITOR`로 보면 `GET`(앞단 1차 검증) → `GET`(워커 2차 검증) → `INCR`(워커) → `PEXPIREAT`(처음 만든 키의 TTL) 순서로 네 명령이 온다. `expireAt(Instant)`는 `EXPIREAT`가 아니라 밀리초 단위 `PEXPIREAT`로 나간다.
- **재현 확인** (Claude 검증, `results/claude-verification/stage0/`). 쿠폰 하나에 서로 다른 사용자가 한꺼번에 요청했다. 모두 워커 소비자 4개(기본값)다.

  | 제한 수량 | 요청 수 (동시 사용자) | 발급 성공 응답 | 실제 발급 | 미발급 | 과발급 | Time Gap 최소 / 평균 / 최대 |
  |---|---|---|---|---|---|---|
  | 100 | 300 (100) | 300 | 100 | 200 | 0 | 47ms / 168ms / 256ms |
  | 10,000 | 12,000 (200) | 12,000 | 10,000 | 2,000 | 0 | 18ms / 4.8초 / 6.3초 |

  - **원문의 미발급이 생긴다.** 요청 전부가 "발급 성공"을 받았지만 발급은 제한 수량까지였다. 1차 검증은 한 번도 마감(409)을 돌려주지 않았다. 워커가 수량을 올리기 전에 요청이 모두 들어왔기 때문이다.
  - **미발급 비율은 원문보다 훨씬 높았다.** 원문의 부하 테스트는 성공 응답 10,162건에 미발급 162건(1.62%)이었는데, 여기서는 12,000건에 2,000건이다. 원문은 워커가 거의 따라가는 상태(Time Gap 수십 ms)였고, 여기서는 워커가 요청 속도(초당 약 1,900~2,300건)를 따라가지 못해 큐가 쌓였다(Time Gap 평균 4.8초). 미발급 수는 Time Gap 동안 1차를 통과한 요청 수다. 1단계에서 요청 속도와 워커 동시 처리 수를 원문 규모에 맞춘다.
  - **과발급은 기본 설정에서는 0건이었다.** 워커 소비자를 32개로 올리면(`WORKER_CONCURRENCY=32`) 제한 100에 요청 300을 5번 보냈을 때 4번에서 9·13·14·21건이 넘게 발급됐다(`results/claude-verification/stage0/exploration/`). 원문이 든 "GET/INCR 원자성 부재 → 수량 오버플로우"도 최신 버전에서 생긴다. 왜 소비자 수에 따라 다른지는 2단계에서 본다.
- **Time Gap은 요청이 적어도 있다.** 요청 1건의 1차 검증 통과부터 워커 수신까지 약 12~50ms였다(MQ 발행·수신과 소비자 스레드 깨우기). 원문 그림의 "MQ 발행 10ms, Worker 수신 50ms"와 비슷한 크기다.
- **원문과 다른 점·줄인 것:** Kotlin 대신 Java. 워커는 별도 인스턴스가 아니라 같은 앱의 소비자 스레드. 유저별 키(1인 1매)와 워커의 DB 처리 실패(원문 시도 1의 롤백)는 넣지 않았다. 원문의 시도 1~3은 3단계에서 스위치로 더한다.

### 직접 확인해 보기

```bash
./gradlew bootJar
```

```bash
docker compose up -d --build
```

앱이 뜨면(`docker compose logs -f app`에서 `Started FcfsCouponApplication`) 발급 요청 1건이 Redis에 어떤 명령으로 가는지 본다. 터미널 1:

```bash
docker compose exec redis redis-cli MONITOR
```

터미널 2:

```bash
curl -s -X POST 'localhost:8080/experiments/reset?couponId=C001&limit=100'; echo; curl -s -X POST 'localhost:8080/coupons/C001/issue?userId=1'; echo
```

터미널 1에 `GET`, `GET`, `INCR`, `PEXPIREAT`가 찍힌다. 보고 나서 Ctrl+C로 끝낸다. 이어서 제한 100개에 300명이 한꺼번에 요청한다.

```bash
curl -s -X POST 'localhost:8080/experiments/reset?couponId=C001&limit=100' && REQUESTS=300 VUS=100 k6 run k6/issue.js
```

```bash
curl -s 'localhost:8080/experiments/summary?couponId=C001' | python3 -m json.tool
```

**관찰 포인트**
- k6의 `issue_success_responses`와 집계의 `successResponses`, `issued`, `unissued`는 어떤 관계인가? `queued`가 0인지도 본다.
- MONITOR에서 앞단의 `GET`과 워커의 `GET`·`INCR` 사이에 시간이 얼마나 비는가? 그 사이에 다른 요청이 들어오면 무엇을 보게 될까?
- RabbitMQ 관리 화면(http://localhost:15672, replay / replay)의 `coupon-issue` 큐에서 소비자 수와 메시지 흐름을 볼 수 있다.
