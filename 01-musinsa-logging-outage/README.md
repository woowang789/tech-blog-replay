# 01. 무신사 「로그가 서비스를 죽였다」 재현

> 원문: [로그가 서비스를 죽였다 — 관측성과 가용성을 동시에 잡는 법](https://techblog.musinsa.com/%EB%A1%9C%EA%B7%B8%EA%B0%80-%EC%84%9C%EB%B9%84%EC%8A%A4%EB%A5%BC-%EC%A3%BD%EC%98%80%EB%8B%A4-4013e35a463b) (무신사 테크 블로그, 2026-10-01)

## 원문 요약

- **장애:** 트래픽이 많은 서비스에서 DEBUG 로그가 켜진 채 트래픽이 몰렸다. 로그량이 평소의 약 100배가 되면서 stdout 파이프 버퍼(약 64KB)가 가득 찼고, 요청 스레드들이 `write` 시스템 콜에서 멈췄다. 이 스레드들이 DB 커넥션을 반납하지 못해 HikariCP가 고갈됐고, 요청이 30초(커넥션 획득 타임아웃 기본값) 주기로 한꺼번에 실패했다.
- **배경:** 전사 표준 로깅 라이브러리는 trace_id를 OpenTelemetry `Span.current()`에서 읽는다. AsyncAppender를 쓰면 이 값을 워커 스레드에서 읽게 되어 빈 값이 나온다. 그래서 표준 가이드가 AsyncAppender를 금지했고, 서비스들이 동기 로깅으로 돌아갔다.
- **해결:** AsyncAppender를 상속한 `TraceAwareAsyncAppender`를 만들었다. `append()`에서 아직 caller 스레드일 때 trace context를 캡처해 `TraceStampedEvent` 래퍼에 담아 큐에 넣는다. 큐가 차면 `neverBlock=true` 설정에 따라 로그를 버리고 요청 스레드는 기다리지 않는다.
- **검증 수치:** 초당 수백 줄에서는 로그 유실과 trace_id 결측이 모두 0%. 초당 약 1,500줄에서 drop 약 33%, 초당 1만 5천 줄(20분)에서 drop 약 65%. 출력된 약 313만 줄의 trace_id 결측 0%. 요청당 로그 횟수를 30배 바꿔도 p95 29ms 유지.

## 장애 연쇄: 원문이 짚은 네 가지

1. **로그 쓰기는 락 하나로 직렬화된다.** Logback `OutputStreamAppender`(ConsoleAppender의 부모)는 한 번에 한 스레드만 출력 스트림에 쓰게 한다. 한 스레드가 `write`에서 멈추면 나머지는 락을 기다린다.
2. **버퍼는 두 단계다.** JVM의 `BufferedOutputStream`(8KB) → 커널의 stdout 파이프 버퍼(약 64KB). 기본값 `immediateFlush=true`는 로그마다 시스템 콜을 부른다.
3. **임계점은 파이프 뒤 소비자의 처리량이다.** 디스크 IOPS가 아니라 로그를 읽어 가는 쪽(containerd → 로그 파일 → fluent-bit)이 못 따라가면 파이프가 찬다.
4. **커넥션을 쥔 채 멈춘다.** 트랜잭션 안에서 찍은 로그가 막히면 커넥션 보유 시간이 늘어나 풀이 고갈되고, 새 요청은 30초 타임아웃에 걸린다.

## 진행 단계

| 단계 | 내용 | 상태 |
|---|---|---|
| 0. 사전 확인 | 최신 버전(Spring Boot 4.1.1)에서도 같은 조건이 성립하고 재현되는가 | ✅ 완료 |
| 1. 재현 | 수집기가 멈출 때(1-A), 운영 중 DEBUG를 켤 때(1-B) | 🔄 진행 중 |
| 2. 원인 증명 | 스레드 덤프, 락 주인, 커널 대기 지점으로 연쇄를 한 단계씩 증명 | |
| 3. 원문 주장 검증 | 64KB, `immediateFlush`, 소비자 처리량 임계점, 30초 주기 burst가 나타나는 조건, trace_id 누락, drop 비율, caller 비용 | |
| 4. 해결책 비교 | 원문의 `TraceAwareAsyncAppender`, OpenTelemetry의 MDC 연동, 큐 정책(`neverBlock`, `discardingThreshold`) | |
| 5. 원문 너머 | 가상 스레드라면 달라지나? 지속 부하에서는? | |

## 실험 환경

```
k6 (초당 50건, open model: 서버가 느려져도 요청은 계속 들어온다)
 │
 ▼
app 컨테이너
 Tomcat 스레드 200개 ─▶ @Transactional ─▶ HikariCP (풀 10개, 획득 타임아웃 30초) ─▶ MySQL
                          │ log.info / log.debug (커넥션을 쥔 채로 찍힌다)
                          ▼
                 Logback ConsoleAppender (Spring Boot 기본값, 동기)
                          │ write()
                          ▼
                 stdout 파이프 (커널 버퍼 약 64KB)
                          │
                          ▼
                 pv: 로그 수집기 역할. LOG_CONSUMER_RATE(기본 초당 16KB)만큼만 읽는다 ─▶ docker logs
```

수집기 속도는 실행 중에도 `./scripts/consumer.sh rate 64k`처럼 바꿀 수 있다.

**pv를 넣은 이유:** 운영에서는 containerd → 로그 파일 → fluent-bit가 파이프를 읽는다. 로컬 Docker의 로그 드라이버는 이 정도 부하에서는 병목이 되지 않아서, 파이프와 docker logs 사이에 속도를 조절할 수 있는 소비자(pv)를 끼웠다. 원문이 말하는 메커니즘(커널 파이프 버퍼가 차면 `write`가 막힌다)은 같은 커널 파이프라서 그대로다.

| 구성 요소 | 버전 |
|---|---|
| Spring Boot | 4.1.1 |
| Logback | 1.5.38 |
| HikariCP | 7.0.2 |
| Hibernate | 7.4.5.Final |
| Tomcat | 11.0.24 |
| MySQL | 8.4 |
| Java | 21 (Eclipse Temurin) |

## 0단계: 사전 확인 결과

- Spring Boot 4.1.1의 기본 콘솔 로깅은 여전히 동기 `ConsoleAppender`다. jar 안의 `DefaultLogbackConfiguration`과 `console-appender.xml`에 AsyncAppender가 없다.
- Logback 1.5.38의 `OutputStreamAppender`는 `streamWriteLock`(ReentrantLock) 하나로 쓰기를 직렬화한다.
- 아래 1단계 실험으로 최신 버전에서도 재현되는 것을 확인했다. 수집기를 멈추거나 DEBUG를 켜면 수 초 안에 `active=10, idle=0, pending=190`, Tomcat 스레드 200개가 모두 묶인다. 스레드 덤프에서는 로그 락의 주인이 stdout `write`에서 멈춘 스레드이고, 그 스레드와 락 대기 스레드 9개가 커넥션 10개를 모두 쥐고 있다.

## 1단계: 재현

### 준비

```bash
./gradlew bootJar
docker compose up -d --build
mkdir -p results
curl localhost:8080/products/1
```

### 실험 1-A: 로그 수집기가 멈추면

수집기를 강제로 멈춰서, 로그 발생량과 상관없이 파이프가 차는 상황을 만든다. 터미널 세 개를 쓴다.

```bash
# 터미널 1: 커넥션 풀과 Tomcat 스레드 상태를 1초마다 출력
./scripts/pool.sh
```

```bash
# 터미널 2: 초당 50건, 2분 30초 부하
DURATION=150s k6 run --out csv=results/k6-1a.csv k6/load.js
```

```bash
# 터미널 3: 부하 시작 20초쯤 뒤 수집기 정지 → 40초 뒤 스레드 덤프 → 30초 뒤 재개
./scripts/consumer.sh pause
./scripts/thread-dump.sh
./scripts/consumer.sh resume
```

부하가 끝나면 시간대별 성공/실패를 본다.

```bash
python3 scripts/k6_timeline.py results/k6-1a.csv
```

**관찰 포인트**
- 수집기를 멈춘 뒤 `active`, `pending`, `tomcatBusy`가 어떻게 변하는가?
- 스레드 덤프 요약에서 1)~3)번 스레드가 각각 몇 개인가? 로그 락의 주인은 누구인가?
- 수집기를 멈춘 동안 응답(성공이든 실패든)이 하나라도 나가는가?

### 실험 1-B: 운영 중에 DEBUG를 켜면

원문의 실제 장애 상황이다. 수집기는 초당 16KB(`LOG_CONSUMER_RATE` 기본값)로 계속 읽고 있고, 평소 로그량(초당 약 7KB)은 충분히 감당한다. 여기서 DEBUG를 켜면 요청 하나가 로그를 30줄 더 남겨 로그량이 초당 약 270KB로 늘어난다.

```bash
# 터미널 1
./scripts/pool.sh
```

```bash
# 터미널 2: 초당 50건, 3분 20초 부하
DURATION=200s k6 run --out csv=results/k6-1b.csv k6/load.js
```

```bash
# 터미널 3: 부하 시작 20초쯤 뒤 DEBUG 켜기 → 100초쯤 뒤 끄기
./scripts/debug.sh on
./scripts/debug.sh off
```

```bash
python3 scripts/k6_timeline.py results/k6-1b.csv
```

**관찰 포인트**
- DEBUG를 켠 뒤 실패가 고르게 나오는가, 몰려서 나오는가? 몰린다면 간격은?
- DEBUG를 끄면 얼마나 빨리 회복되는가?

### 생각해 볼 질문 (2단계에서 증명한다)

1. 수집기를 멈춘 순간이 아니라 몇 초 뒤에 장애가 시작되는 이유는?
2. 1-A에서 커넥션을 기다리던 스레드는 30초가 지나면 타임아웃이 나는데, 왜 실패 응답조차 바로 나가지 않을까?
3. 1-B에서 실패가 왜 30초마다 몰려서 나올까? 커넥션 획득 타임아웃이 30초라는 것만으로 설명이 될까?
4. 1-B를 `./scripts/consumer.sh rate 64k`로 수집기를 네 배 빠르게 한 뒤 다시 하면 실패 패턴이 어떻게 달라질까? 왜?

> **k6의 `dropped_iterations`에 대해:** 응답이 수십 초씩 걸리면 동시에 붙잡힌 가상 사용자가 수천 명 필요하다. k6가 실행 중에 가상 사용자를 늘리는 속도가 못 따라가면 보내지 못한 요청이 `dropped_iterations`로 집계된다. 실제 서비스였다면 그만큼 요청이 더 쌓였을 것이므로 결론에는 영향이 없다.

## 1단계 결과

직접 돌려 보고 채운다.

| 관찰 항목 | 1-A (수집기 정지) | 1-B (DEBUG 켜기) |
|---|---|---|
| 원인을 건 뒤 풀이 고갈될 때까지 걸린 시간 | | |
| 장애 중 `active` / `pending` / `tomcatBusy` | | |
| 장애 중 5초당 성공 응답 수 | | |
| 실패 응답이 나온 패턴 | | |
| 스레드 덤프: write 멈춤 / 락 대기 / 커넥션 대기 | | |
| 원인을 없앤 뒤 회복까지 걸린 시간 | | |
