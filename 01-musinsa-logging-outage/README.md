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
   - 재현해 보니 콘솔 출력에서는 다르다. Spring Boot 기본 콘솔 출력이 쓰는 `System.out`은 JDK가 128바이트 버퍼에 쓸 때마다 비우는 설정(autoFlush)으로 만든다. 그래서 `immediateFlush`를 꺼도 로그 한 줄마다 쓰기 시스템 콜이 한 번 나갔다(로그 1만 줄에 10,006회, `immediateFlush=false`에서 10,003회). `docker compose exec app javap -c -p java.lang.System`의 `newPrintStream`에서 확인할 수 있다.
3. **임계점은 파이프 뒤 소비자의 처리량이다.** 디스크 IOPS가 아니라 로그를 읽어 가는 쪽(containerd → 로그 파일 → fluent-bit)이 못 따라가면 파이프가 찬다.
4. **커넥션을 쥔 채 멈춘다.** 트랜잭션 안에서 찍은 로그가 막히면 커넥션 보유 시간이 늘어나 풀이 고갈되고, 새 요청은 30초 타임아웃에 걸린다.

## 진행 단계

| 단계 | 내용 | 상태 |
|---|---|---|
| 0. 사전 확인 | 최신 버전(Spring Boot 4.1.1)에서도 같은 조건이 성립하고 재현되는가 | ✅ 완료 |
| 1. 재현 | 수집기가 멈출 때(1-A), 운영 중 DEBUG를 켤 때(1-B) | ✅ 완료 |
| 2. 원인 증명 | 커널, JVM, 커넥션 풀, MySQL에서 각각 증거를 잡아 연쇄를 한 고리씩 증명 | ✅ 완료 |
| 3. 해결책 재현 | 원문의 `TraceAwareAsyncAppender`를 같은 장애 조건에서 재현하고, 원문의 검증(trace_id 보존, 로그 버림, 요청 스레드 비용)을 따라 한다 | ✅ 완료 |
| 4. 원문 너머 | 가상 스레드라면 달라지나? 지속 부하에서는? | |

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

**pv를 넣은 이유:** 운영에서는 컨테이너 런타임(containerd)이 파이프를 읽어 노드의 로그 파일에 쓰고, fluent-bit 같은 수집기가 그 파일을 읽어 간다. 로컬 Docker의 로그 드라이버는 이 정도 부하에서는 병목이 되지 않아서, 파이프와 docker logs 사이에 속도를 조절할 수 있는 소비자(pv)를 끼웠다. 원문이 말하는 메커니즘(커널 파이프 버퍼가 차면 `write`가 막힌다)은 같은 커널 파이프라서 그대로다.

| 구성 요소 | 버전 |
|---|---|
| Spring Boot | 4.1.1 |
| Logback | 1.5.38 |
| HikariCP | 7.0.2 |
| Hibernate | 7.4.5.Final |
| Tomcat | 11.0.24 |
| MySQL | 8.4 |
| Java | 21 (Eclipse Temurin) |
| OpenTelemetry Java 에이전트 / API | 2.32.0 / 1.62.0 (3단계부터) |

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

### 스레드 덤프 뜨는 법

스레드 덤프는 JVM 안의 모든 스레드가 **지금 이 순간 어떤 코드를 실행하고 있는지(스택)** 찍은 사진이다. 장애가 진행 중일 때 떠야 의미가 있다.

| 방법 | 명령 | 비고 |
|---|---|---|
| 이 프로젝트 스크립트 | `./scripts/thread-dump.sh` | 컨테이너 안에서 아래 `jcmd`를 실행해 `results/`에 저장하고 분류 요약을 출력한다 |
| jcmd (JDK 도구) | `jcmd <pid> Thread.print -l` | 권장 방식. `-l`을 붙여야 ReentrantLock 같은 락의 주인까지 나온다 |
| jstack (JDK 도구) | `jstack -l <pid>` | 예전부터 쓰던 도구. 결과는 거의 같다 |
| Actuator | `curl -H 'Accept: text/plain' localhost:8081/actuator/threaddump` | HTTP로 받는다. 관리 포트가 분리돼 있어 장애 중에도 응답한다. 다만 커널 스레드 ID(nid)가 없다 |
| kill -3 | `kill -3 <pid>` | 덤프를 JVM의 **stdout**으로 출력한다. stdout이 막힌 이 장애에서는 덤프가 나오지 않으니 쓰면 안 된다 |

`<pid>`는 컨테이너 안 java 프로세스 번호다(`docker compose exec app pgrep -x java`). `jcmd`, `jstack`은 JDK에 들어 있어서 앱 이미지를 JRE가 아니라 JDK로 만들었다.

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

터미널 3에서는 아래 명령을 **시간 간격을 두고 하나씩** 실행한다.

1. 부하 시작 20초쯤 뒤, 수집기 정지

   ```bash
   ./scripts/consumer.sh pause
   ```

2. 정지 40초쯤 뒤, 스레드 덤프. 장애가 진행 중일 때 떠야 의미가 있다. `results/thread-dump-시각.txt`에 저장되고 분류 요약이 바로 출력된다. (아래 "스레드 덤프 뜨는 법" 참고)

   ```bash
   ./scripts/thread-dump.sh
   ```

3. 덤프 30초쯤 뒤, 수집기 재개

   ```bash
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

터미널 3에서는 아래 명령을 시간 간격을 두고 하나씩 실행한다.

1. 부하 시작 20초쯤 뒤, DEBUG 켜기

   ```bash
   ./scripts/debug.sh on
   ```

2. 켠 뒤 60초쯤, 스레드 덤프

   ```bash
   ./scripts/thread-dump.sh
   ```

3. 켠 뒤 100초쯤, DEBUG 끄기. 30초 주기 실패가 반복되는 걸 보려면 이만큼은 켜 둬야 한다.

   ```bash
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

### 1단계 결과

직접 실행(2026-10-07~08)한 값은 **(직접)**, Claude가 검증하며 돌린 값(`results/claude-verification/`)은 **(검증)**으로 구분했다. 직접 실행은 절차보다 짧게 돌아서, 1-A는 30초가 되기 전에 재개했고 1-B는 DEBUG를 약 30초만 켰다.

| 관찰 항목 | 1-A (수집기 정지) | 1-B (DEBUG 켜기) |
|---|---|---|
| 원인을 건 뒤 풀이 고갈될 때까지 걸린 시간 | 약 10초 (검증: 정지 9초 뒤) | 2초 이내 (검증) |
| 장애 중 `active` / `pending` / `tomcatBusy` | 10 / 190 / 200 (검증) | 10 / 189 / 200 (직접: 앱 로그의 HikariCP 메시지 `waiting=189`, 검증: `tomcatBusy` 200) |
| 장애 중 5초당 성공 응답 수 | 0 (직접: 28초 동안 응답 0건) | 10~18건, 초당 약 2.8건 (직접) |
| 실패 응답이 나온 패턴 | 직접: 28초 만에 재개해서 실패 0건, 가장 느린 요청 29.4초. 검증: 30초를 넘기자 503 190건이 재개 직후 한꺼번에 나옴 | 직접: DEBUG를 켜고 약 30초 뒤 첫 무리 14건(응답 시간 30.0~30.6초). 검증: 100초 켜 두자 31~34초 간격으로 반복 |
| 스레드 덤프: write 멈춤 / 락 대기 / 커넥션 대기 | 1 / 67 / 132 (검증. 락 대기 중 커넥션 보유 9, 타임아웃 뒤 실패 로그 58) | 1 / 9 / 190 (검증) |
| 원인을 없앤 뒤 회복까지 걸린 시간 | 약 4초 (검증) | 약 15초 (직접: 밀린 요청을 처리한 뒤 정상) |

**1단계에서 새로 알게 된 것:** 커넥션 획득이 타임아웃된 스레드는 503을 보내기 전에 로그 두 줄을 쓴다. Hibernate가 예외를 변환하면서 남기는 WARN 한 줄과 예외 핸들러의 WARN 한 줄이다. 이 로그도 같은 락과 꽉 찬 파이프를 지나야 해서, 수집기가 멈춰 있으면 실패 응답조차 나가지 못한다.

## 2단계: 원인 증명

1단계에서 추론한 연쇄를 **층마다 다른 도구로 직접 증거를 잡아** 한 고리씩 확인한다. 같은 순간을 커널, JVM, 커넥션 풀, MySQL이 각자 어떻게 보는지 맞춰 보는 것이 핵심이다.

| 고리 | 주장 | 증거 | 보는 곳 |
|---|---|---|---|
| ① 파이프가 찬다 | write에서 멈춘 스레드는 커널의 파이프 쓰기에서 잠들어 있다 | 실행 중인 시스템 콜이 `write(fd 1)`, 잠든 위치가 `pipe_write` | 커널 `/proc/<pid>/task/<tid>/` |
| ② 락이 줄을 세운다 | 그 스레드가 Logback 출력 락의 주인이고, 나머지는 그 락을 기다린다 | 락 주인의 nid가 ①의 tid와 같다 | 스레드 덤프 |
| ③ 커넥션을 쥔 채 멈춘다 | 멈춘 스레드들이 커넥션 10개를 모두 쥐고 있고, DB는 놀고 있다 | 열린 트랜잭션 10개, 실행 중인 쿼리 0개, 커넥션은 `Sleep` | MySQL `information_schema` |
| ④ 풀이 고갈된다 | 나머지 요청은 커넥션을 기다린다 | `pending`, 덤프의 `HikariPool.getConnection` | Actuator, 스레드 덤프 |
| ⑤ 실패도 로그에 막힌다 | 30초 타임아웃 뒤 스레드는 Hibernate의 실패 로그에서 멈춘다 | 타임아웃 뒤 덤프의 `SqlExceptionHelper` 락 대기 | 스레드 덤프 |
| ⑥ 순서 | 원인이 먼저, 결과가 정해진 간격으로 뒤따른다 | 정지 → write 대기 → 풀 고갈 → 30초 뒤 타임아웃 | 1초 간격 타임라인 |

### 새 도구

| 스크립트 | 하는 일 |
|---|---|
| `scripts/watch-chain.sh` | 모든 층을 1초 간격으로 한 줄씩 출력하는 타임라인 |
| `scripts/evidence.sh` | 지금 이 순간의 층별 증거를 `results/evidence-시각/`에 모으고, 층끼리 맞춰 본 요약을 출력 |

`watch-chain.sh`의 열

| 열 | 뜻 | 출처 |
|---|---|---|
| `collector` | 로그 수집기(pv) 상태. `STOPPED`면 멈춘 상태 | 커널 `/proc/<pv pid>/stat` |
| `writeBlocked` | stdout(fd 1)에 write 하다 잠든 java 스레드 수 | 커널 `/proc/<java pid>/task/*/syscall` |
| `active`, `pending`, `timeoutTotal`, `tomcatBusy` | 1단계 `pool.sh`와 같다 | Actuator |
| `openTrx` | 열린 트랜잭션 수 | MySQL `information_schema.innodb_trx` |
| `oldestTrx` | 가장 오래 열려 있는 트랜잭션의 나이 | MySQL `information_schema.innodb_trx` |
| `runningSql` | 지금 실제로 쿼리를 실행 중인 트랜잭션 수 | MySQL `information_schema.innodb_trx` |

커널 정보는 컨테이너 안에서 root로 `/proc`을 읽어서 얻는다. 시스템 콜 번호는 CPU마다 달라서(write는 Apple Silicon 같은 aarch64에서 64, x86_64에서 1) 스크립트가 알아서 고른다. 한 줄마다 컨테이너 접속과 MySQL 조회를 하느라 실제로는 1.5초 정도 간격으로 찍힌다.

### 실험 2-A: 수집기를 멈추고 층마다 증거 잡기

```bash
# 터미널 1: 연쇄 타임라인 (화면에 보이면서 results/에도 저장)
./scripts/watch-chain.sh | tee "results/chain-$(date +%H%M%S).txt"
```

```bash
# 터미널 2: 초당 50건, 2분 30초 부하
DURATION=150s k6 run k6/load.js
```

터미널 3에서는 아래 명령을 시간 간격을 두고 하나씩 실행한다.

1. 부하 시작 20초쯤 뒤, 수집기 정지

   ```bash
   ./scripts/consumer.sh pause
   ```

2. 정지 15초쯤 뒤, 증거 1 (타임아웃 전)

   ```bash
   ./scripts/evidence.sh
   ```

3. 정지 50초쯤 뒤, 증거 2 (타임아웃 뒤). 명령은 2번과 같다.

   ```bash
   ./scripts/evidence.sh
   ```

4. 그다음 수집기 재개

   ```bash
   ./scripts/consumer.sh resume
   ```

**관찰 포인트**
- 타임라인: 수집기를 멈추고 몇 초 뒤 `writeBlocked`가 1이 되는가? 그 직후 나머지 열은 어떤 순서로 바뀌는가? `oldestTrx`는 어떻게 늘어나고, `timeoutTotal`은 언제 오르는가? 재개하면 어떤 순서로 풀리는가?
- 증거 1(타임아웃 전): 커널에서 잠든 스레드와 로그 락의 주인이 같은 스레드인가? 커넥션 수 세 가지(HikariCP, 덤프, MySQL)가 같은가? MySQL에서 실행 중인 쿼리는 몇 개인가?
- 증거 2(타임아웃 뒤): 락을 기다리는 스레드들은 무엇을 하다 멈췄는가?

### 생각해 볼 질문 (2단계)

1. 스레드 덤프에서는 `RUNNABLE`인 스레드가 커널에서는 잠들어(`S`) 있다. CPU 사용률이나 RUNNABLE 스레드 수만 보는 모니터링에는 이 장애가 어떻게 보일까?
2. 장애 중 MySQL의 커넥션 10개는 모두 `Sleep`이고 실행 중인 쿼리는 0개다. "DB는 한가한데 커넥션 풀은 고갈됐다"는 상황을 만나면 무엇부터 의심해야 할까?
3. `writeBlocked`는 장애 내내 1에서 더 늘지 않는다. 요청 스레드는 수백 개인데 왜 write에서 잠든 스레드는 하나뿐일까?
4. 재개하면 어떤 순서로 풀리는가? 그 순서는 장애가 번진 순서와 어떤 관계인가?

### 2단계 결과

직접 실행(2026-10-08 11:50~11:51)한 증거 스냅샷 두 장(`results/evidence-115059`, `results/evidence-115136`)으로 채웠다.

| 증거 | 증거 1 (11:50:59, 타임아웃 전) | 증거 2 (11:51:36, 타임아웃 뒤) |
|---|---|---|
| ① 커널: write(fd 1)에서 잠든 스레드 (tid, 상태, 잠든 위치) | tid 48 `http-nio-8080-exec-7`, S, `pipe_write` | 같은 tid 48, S, `pipe_write`. 37초 뒤에도 같은 자리이고 `cpu=325.14ms`가 그대로다 |
| ② 로그 락 주인이 ①의 스레드인가 | 같다 | 같다 |
| ② 락 대기: 커넥션 보유 / 실패 로그 / 기타 | 9 / 0 / 0 | 9 / 190 / 0 |
| ③ 커넥션 수: HikariCP active / 덤프의 커넥션 보유 스레드 / MySQL 열린 트랜잭션 | 10 / 10 / 10 | 10 / 10 / 10 |
| ③ MySQL: 실행 중인 쿼리 / 커넥션 상태 | 0개 / 10개 모두 Sleep (가장 오래된 트랜잭션 12초째) | 0개 / 10개 모두 Sleep (가장 오래된 트랜잭션 50초째) |
| ④ HikariCP pending / 덤프의 커넥션 대기 스레드 | 190 / 190 | 0 / 0 (190건 모두 타임아웃) |

직접 실행의 타임라인(터미널 1 출력)은 저장하지 않아서, 증거에서 역산할 수 있는 값은 **(직접)**, 나머지는 Claude 검증 실행(`results/claude-verification/stage2/chain.txt`)의 값을 **(검증)**으로 적었다.

| 타임라인 (⑥) | 걸린 시간 |
|---|---|
| 수집기 정지 → `writeBlocked` 1 | 10초 (검증) |
| `writeBlocked` 1 → 커넥션 풀 고갈(`active` 10) | 같은 샘플에서 함께 바뀜, 1.5초 이내 (검증) |
| 풀 고갈 → 첫 타임아웃(`timeoutTotal` 증가) | 약 30초. 직접: 가장 오래된 트랜잭션 나이로 역산하면 풀 고갈은 11:50:47쯤이고, 증거 1 때 0건이던 타임아웃이 증거 2 때 190건 |
| 수집기 재개 → 회복(`active` 0, `tomcatBusy` 0) | 약 5초 (검증) |

**2단계에서 새로 알게 된 것**
- JVM이 RUNNABLE로 본 스레드는 14개였지만, 커널에서 실제로 실행 중(R)인 스레드는 1개였다. 나머지 245개는 모두 잠든 상태(S)였다.
- 커넥션 풀이 고갈된 동안 MySQL은 쿼리를 하나도 실행하지 않았다. 커넥션 10개가 트랜잭션을 연 채 50초 동안 아무 일도 하지 않았다.


## 3단계: 원문의 해결책 재현

원문의 흐름을 같은 장애 조건(1-B)에서 그대로 따라간다.

1. **동기 출력** (원문의 표준 구성): trace_id는 남지만, 로그가 몰리면 서비스가 멈춘다.
2. **기본 AsyncAppender** (원문의 딜레마): 서비스는 멈추지 않지만 trace_id가 빈 값이 된다.
3. **TraceAwareAsyncAppender** (원문의 해결책): 서비스도 멈추지 않고 trace_id도 남는다. 대신 큐가 차면 로그를 버린다.

세 경우 모두 OpenTelemetry 에이전트를 붙이고, 원문의 표준 로깅 라이브러리처럼 로그를 문자열로 만드는 순간 `Span.current()`에서 trace_id를 읽는다. 바꾸는 것은 출력 방식 하나뿐이다.

### 원문의 해결책 코드

| 파일 | 하는 일 |
|---|---|
| `logging/TraceAwareAsyncAppender` | 원문 코드와 같다. `AsyncAppender`를 상속해 `append()`만 바꿨다. 큐에 넣기 전, 아직 caller 스레드일 때 `Span.current()`로 trace_id와 span_id를 읽어 이벤트에 담는다 |
| `logging/TraceStampedEvent` | 원본 로그 이벤트를 감싸서 모든 동작은 그대로 위임하고, 캡처한 trace_id와 span_id만 더 들고 간다 |
| `logging/OtelTraceIdConverter`, `OtelSpanIdConverter` | 로그를 문자열로 만들 때 trace_id를 채운다. `TraceStampedEvent`면 캡처해 둔 값을, 아니면 그 순간의 `Span.current()`를 쓴다 |
| `src/main/resources/logback-spring.xml` | 출력 방식을 고르는 스위치. `trace-aware`는 원문처럼 `neverBlock=true`(큐가 가득 차면 기다리지 않고 버림)이고, 나머지는 Logback 기본값이다 |

### 실험 도구

| 파일 | 하는 일 |
|---|---|
| `scripts/scenario.sh <이름>` | 지금 떠 있는 설정 그대로 1-B 장애 조건(초당 50건 100초, 시작 15초 뒤 DEBUG를 켜고 60초 뒤 끔)을 자동으로 돌린다. 결과를 `results/compare-<이름>/`에 남기고 요약을 출력한다 |
| `scripts/compare_report.py` | 결과 디렉터리 여러 개를 한 표로 비교한다 |
| `scripts/trace-check.sh` | `traceparent` 헤더로 보낸 trace_id가 로그에 그대로 찍히는지 센다. 원문이 말한 "서비스를 넘어 같은 trace_id가 이어진다"를 확인한다 |
| `GET /experiments/logging-config` | 지금 붙어 있는 appender와 설정값. 스위치가 실제로 적용됐는지 확인할 때 쓴다 |
| OpenTelemetry Java 에이전트 2.32.0 | 빌드할 때 Maven Central에서 받아 이미지에 넣는다. `OTEL_AGENT=on`일 때만 붙고, 추적 데이터를 밖으로 보내지는 않는다 |

스위치는 docker-compose의 환경 변수다. 변수를 앞에 붙여 `docker compose up -d`로 다시 띄우면 바뀌고, 변수 없이 `docker compose up -d`를 하면 기본값(1·2단계와 같은 상태)으로 돌아온다.

| 변수 | 기본값 | 뜻 |
|---|---|---|
| `OTEL_AGENT` | `off` | `on`이면 OpenTelemetry 에이전트를 붙인다 |
| `SPRING_PROFILES_ACTIVE` | 없음 | `trace`: 로그에 trace_id를 넣는다. 여기에 `async`(기본 AsyncAppender)나 `trace-aware`(원문의 해결책)를 더하면 출력 방식이 바뀐다 |
| `DEBUG_LINES_PER_REQUEST` | `30` | DEBUG를 켰을 때 요청 한 건이 더 남기는 로그 줄 수 (3-D) |

`scenario.sh` 요약의 열

| 열 | 뜻 |
|---|---|
| DEBUG 동안 성공/초 | DEBUG를 켠 60초 동안 끝난 성공 응답 수 ÷ 60. 부하는 초당 50건이다 |
| 503 | 커넥션 획득 실패 응답 수 |
| p95, 최대 | 전체 요청의 응답 시간 |
| 회복 | DEBUG를 끈 뒤, 1초 넘게 걸린 응답이 마지막으로 끝나기까지 걸린 시간 |
| 로그 이벤트, 출력된 줄, 버림 | 앱이 남기려 한 로그 수(`logback.events` 메트릭), 그중 수집기를 지나 실제로 출력된 줄 수, 버려진 비율 |
| trace_id 빈 줄 | 출력된 요청 스레드 로그 중 trace_id가 빈 줄 수 / trace_id 칸이 있는 줄 수 |

### 준비

코드와 이미지가 바뀌었으니 다시 빌드한다.

```bash
./gradlew bootJar
```

```bash
docker compose up -d --build
```

실험이 도는 동안 진행을 보려면 다른 터미널에 커넥션 풀 상태를 띄워 둔다.

```bash
./scripts/pool.sh
```

### 실험 3-A: 동기 출력 (원문의 표준 구성)

```bash
OTEL_AGENT=on SPRING_PROFILES_ACTIVE=trace docker compose up -d
```

```bash
./scripts/trace-check.sh
```

```bash
./scripts/scenario.sh sync
```

### 실험 3-B: 기본 AsyncAppender (원문의 딜레마)

```bash
OTEL_AGENT=on SPRING_PROFILES_ACTIVE=trace,async docker compose up -d
```

```bash
curl -s localhost:8080/experiments/logging-config
```

```bash
./scripts/trace-check.sh
```

```bash
./scripts/scenario.sh async
```

### 실험 3-C: TraceAwareAsyncAppender (원문의 해결책)

```bash
OTEL_AGENT=on SPRING_PROFILES_ACTIVE=trace,trace-aware docker compose up -d
```

```bash
curl -s localhost:8080/experiments/logging-config
```

```bash
./scripts/trace-check.sh
```

```bash
./scripts/scenario.sh trace-aware
```

세 결과를 한 표로 본다.

```bash
python3 scripts/compare_report.py results/compare-sync results/compare-async results/compare-trace-aware
```

시간대별 성공·실패는 1단계 때처럼 본다.

```bash
python3 scripts/k6_timeline.py results/compare-trace-aware/k6.csv
```

**관찰 포인트 (3-A~3-C)**
- `trace-check.sh`: 세 경우 각각 보낸 trace_id가 그대로 찍힌 줄은 몇 줄인가? 세 경우 모두 실제로 출력하는 appender는 같은 `CONSOLE`이다.
- 비교표: 장애 조건에서 성공/초, 503, p95는 어떻게 다른가?
- 비동기 출력에서는 로그를 얼마나 버렸나? 버린 상태에서도 출력된 요청 로그의 trace_id는 빠짐없이 남았나? (원문: 65%를 버린 조건에서도 출력된 로그의 trace_id 결측 0%)

> **버림 비율에 대해:** 원문은 초당 약 1,500줄에서 약 33%, 초당 1만 5천 줄에서 약 65%를 버렸다. 이 실험의 DEBUG 구간도 초당 약 1,550줄(초당 50건 × 요청당 31줄)이지만, 수집기를 장애가 나도록 초당 16KB로 묶어 두었기 때문에 버리는 비율은 원문과 다르다. 원문도 drop이 시작되는 지점과 처리량의 절대값은 환경에 따라 달라진다고 했다.

### 실험 3-D: 요청 스레드가 치르는 비용

원문은 캡처 로직과 큐에 넣는 비용이 요청 스레드에 부담을 주는지 따로 쟀다. 초당 로그량을 약 1만 5천 줄로 맞추고 요청당 로그 수만 30배 다르게 해서(초당 50건 × 300줄, 초당 1,500건 × 10줄) 두 경우 모두 p95가 29ms인 것을 확인했다. 여기서는 초당 50건 × 요청당 300줄을 재고, 같은 부하에서 DEBUG를 끈 기준과 비교한다.

1. 요청당 DEBUG 로그를 300줄로 바꿔 띄우고 DEBUG를 켠다.

   ```bash
   OTEL_AGENT=on SPRING_PROFILES_ACTIVE=trace,trace-aware DEBUG_LINES_PER_REQUEST=300 docker compose up -d
   ```

   ```bash
   ./scripts/debug.sh on
   ```

2. 먼저 20초 부하로 데운다. 다시 띄운 직후의 JVM은 아직 JIT 컴파일 전이라 느려서, 그대로 재면 요청 스레드 비용이 아니라 데워지는 시간을 재게 된다. 이 결과는 버린다.

   ```bash
   RATE=50 DURATION=20s k6 run k6/load.js
   ```

3. 30초 잰다.

   ```bash
   RATE=50 DURATION=30s k6 run k6/load.js
   ```

4. DEBUG를 끄고 같은 부하로 기준을 잰다.

   ```bash
   ./scripts/debug.sh off
   ```

   ```bash
   RATE=50 DURATION=30s k6 run k6/load.js
   ```

5. 기본값으로 되돌린다.

   ```bash
   docker compose up -d
   ```

**관찰 포인트**
- 3번과 4번의 `http_req_duration` p95는? 요청 한 건이 로그를 300번 남기는데 응답 시간은 얼마나 늘었나?

**더 해 보기:** 원문의 다른 쪽 조건(초당 1,500건 × 요청당 10줄)도 같은 순서로 잰다. `DEBUG_LINES_PER_REQUEST=10`으로 띄우고 `RATE=1500`으로 돌린다.

### 생각해 볼 질문 (3단계)

1. (3-B) AsyncAppender를 써도 스레드 이름(`[nio-8080-exec-1]`)은 제대로 찍히는데 trace_id는 왜 빈 값일까?
2. (3-C) `TraceAwareAsyncAppender`는 trace_id를 언제, 어느 스레드에서 읽도록 바꿨나? 워커 스레드가 로그를 문자열로 만들 때는 무엇을 쓰나?
3. (3-B, 3-C) 수집기는 여전히 초당 16KB인데 요청 스레드는 왜 더 이상 멈추지 않나? 나머지 로그는 어디로 갔나?
4. (3-D) 요청 한 건이 로그를 300번 남겨도 응답 시간이 크게 늘지 않는다면 왜일까? 버려지는 로그는 메시지를 문자열로 만들기 전에 버려질까, 만든 뒤에 버려질까? (`AsyncAppenderBase.append`를 보자)
5. 원문은 마지막에 "AsyncAppender로도 지속적인 과부하를 모두 해결할 수는 없다"고 했다. 이 해결책이 지켜 주는 것과 지켜 주지 못하는 것은 무엇일까?

### 3단계 결과

직접 실행(2026-10-08 21:08~21:38)한 값은 **(직접)**, Claude가 검증하며 돌린 값(`results/claude-verification/stage3/`)은 **(검증)**으로 구분했다. `trace-check.sh`와 3-D의 k6 결과는 파일로 남지 않아 검증 값으로 채웠다.

**비교표** (직접, `results/compare-*`)

| 이름 | DEBUG 동안 성공/초 | 503 | p95 | 최대 | 회복 | 로그 이벤트 | 출력된 줄 | 버림 | trace_id 빈 줄 |
|---|---|---|---|---|---|---|---|---|---|
| sync | 2.9 | 152 | 50.6s | 60.6s | 35초 | 7,928 | 7,928 | 0.0% | 0/7928 |
| async | 50.0 | 0 | 14ms | 319ms | - | 95,091 | 7,808 | 91.8% | 7808/7808 |
| trace-aware | 50.0 | 0 | 33ms | 374ms | - | 95,151 | 6,756 | 92.9% | 0/6756 |

| 실험 | 관찰 항목 | 결과 |
|---|---|---|
| 3-A 동기 출력 | 보낸 trace_id가 찍힌 줄 / 장애 조건에서 성공/초, 503, p95 | 20/20 (검증) / 초당 2.9건, 503 152건, p95 50.6초 (직접) |
| 3-B 기본 AsyncAppender | 보낸 trace_id가 찍힌 줄 / 장애 조건에서 성공/초, 503, p95, 버림 | 0/20 (검증) / 초당 50건, 503 0건, p95 14ms, 버림 91.8% (직접) |
| 3-C TraceAwareAsyncAppender | 보낸 trace_id가 찍힌 줄 / 장애 조건에서 성공/초, 503, p95, 버림, 부하 중 trace_id 빈 줄 | 20/20 (검증) / 초당 50건, 503 0건, p95 33ms, 버림 92.9%, 빈 줄 0/6,756 (직접) |
| 3-D 요청 스레드 비용 | p95 (DEBUG 300줄 / DEBUG 끈 기준) | 15ms / 7.5ms (검증). 더 해 보기(초당 1,500건 × 10줄)는 4.3ms / 15ms (검증) |

**3단계에서 새로 알게 된 것**
- 기본 AsyncAppender만으로도 장애는 사라졌다. 수집기는 그대로 초당 16KB인데 초당 50건을 모두 처리했고, 대신 로그의 92%를 버렸다. 그리고 출력된 7,808줄 모두 trace_id가 빈 값이었다. 원문의 표준 가이드가 AsyncAppender를 금지한 이유가 이것이다.
- TraceAwareAsyncAppender는 같은 조건에서 로그를 93% 버렸지만, 출력된 요청 로그 6,756줄의 trace_id는 하나도 빠지지 않았다. 원문의 "로그를 버리는 동작과 trace_id를 보존하는 동작이 서로 간섭하지 않는다"와 같다.
- 버림 비율의 절대값은 원문(33%, 65%)과 다르다. 이 환경은 장애를 재현하려고 수집기를 초당 16KB로 묶어 두었기 때문이다.
- 다시 띄운 직후의 JVM으로 응답 시간을 재면 데워지는 시간까지 섞인다. 3-D 검증에서 데우지 않고 잰 초당 1,500건의 p95는 1.7초였고, 20초 데운 뒤에는 4.3ms였다.
