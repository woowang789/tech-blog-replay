# 02. 올리브영 「SQS 기반 알림톡 처리에서 발생한 DB 커넥션 데드락 분석기」 재현

> 원문: [SQS 기반 알림톡 처리에서 발생한 DB 커넥션 데드락 분석기 — 이벤트 기반 구조 전환 이후 마주한 트랜잭션 경합 문제와 해결 과정](https://oliveyoung.tech/2025-12-30/alimtalk_improve_event_driven_architecture/) (올리브영 테크블로그, 2025-12-30)

## 원문 요약

- **배경:** 여러 서비스에 흩어져 있던 알림톡 발송 로직을 SQS 기반 이벤트 구조로 바꿨다. 비즈니스 로직은 SQS에 메시지를 발행하고 바로 다음 일을 한다. 컨슈머가 `@SqsListener`로 메시지를 받아 검증 및 데이터 조회 → 템플릿 생성 → Messaging API 호출 → 알림 내역 저장을 한다.
- **장애:** 배포 뒤 `HikariPool-1 - Connection is not available, request timed out after 30008ms`가 순간 대량으로 났다.
- **원인:** 세 가지가 맞물린 커넥션 데드락이었다.
  1. SQS 리스너는 가져온 메시지를 메시지마다 별도 스레드로 병렬 처리한다.
  2. 동시에 처리하는 메시지 수가 HikariCP `maximumPoolSize`보다 컸다.
  3. 알림 내역 저장에 `REQUIRES_NEW`를 써서 메시지 1건에 커넥션이 2개 필요했다.
  
  모든 스레드가 첫 커넥션을 쥔 채 두 번째 커넥션을 기다렸다.
- **해결:** `REQUIRES_NEW`를 빼서 메시지 1건에 커넥션 1개만 쓰게 했고, 한 번에 가져오는 메시지 수를 커넥션 수 이하로 줄였다.
- **공식:** 데드락을 피하는 최소 커넥션 수 = `Tn × (Cm − 1) + 1`. Tn은 동시에 처리하는 최대 스레드 수, Cm은 스레드 하나가 동시에 쥐는 최대 커넥션 수다. HikariCP의 풀 크기 가이드에서 가져왔다.

## 장애 연쇄

```
SQS에 알림 메시지가 몰린다
  ▼ 리스너가 메시지를 최대 N건 동시에 처리한다 (스레드 N개)
  ▼ 스레드마다 바깥 트랜잭션이 커넥션을 1개씩 쥔다 → N개가 풀을 다 쓴다
  ▼ 알림 내역 저장의 REQUIRES_NEW가 커넥션을 하나 더 달라고 한다 → 남은 커넥션이 없다
  ▼ 모두가 서로가 쥔 커넥션이 풀리기를 기다린다 (데드락)
  ▼ 30초(커넥션 획득 타임아웃) 뒤 한꺼번에 실패한다
```

## 진행 단계

| 단계 | 내용 | 상태 |
|---|---|---|
| 0. 사전 확인 | 최신 버전(Spring Boot 4.1.1, Spring Cloud AWS 4.2.0)에서도 같은 구조가 성립하고 데드락이 재현되는가 | ✅ 완료 |
| 1. 재현 | 메시지가 적을 때(1-A)와 몰릴 때(1-B). 몰리면 커넥션 풀이 멈추고 30초마다 한꺼번에 실패한다 | ✅ 완료 |
| 2. 원인 증명 | 스레드 덤프, 커넥션 풀, MySQL에서 "모두가 커넥션 하나를 쥔 채 하나를 더 기다린다"를 증명하고, 원문 공식의 경계를 확인 | |
| 3. 해결책 재현 | 원문의 두 가지 해결(`REQUIRES_NEW` 제거, 동시 처리 수 줄이기)과 그 효과 | |
| 4. 원문 너머 | 필요하면 정한다 | |

## 실험 환경

```
POST /experiments/notices?count=N   (실험용: 알림 메시지 N건을 SQS에 넣는다)
 │
 ▼
ElasticMQ (로컬 SQS)
 │ 리스너 컨테이너가 큐에서 메시지를 가져와 최대 10건을 동시에 처리한다 (스레드 10개)
 ▼
app 컨테이너
 NoticeListener ─▶ NoticeService.send   @Transactional (커넥션 1)
                    ├ 클레임 조회
                    ├ 가짜 Messaging API 호출 (200ms 동안 커넥션을 쥔 채 기다린다)
                    └ NoticeHistoryService.save   @Transactional(REQUIRES_NEW) (커넥션 2)
 HikariCP (풀 10개, 획득 타임아웃 30초) ─▶ MySQL
```

**ElasticMQ를 쓴 이유:** SQS API를 그대로 흉내 내는 로컬 서버라 Spring Cloud AWS가 실제 SQS처럼 쓴다. 메시지를 몇 건씩 가져와 몇 개의 스레드로 처리할지는 Spring Cloud AWS 쪽 리스너 컨테이너가 정하므로, 로컬 서버를 써도 이 장애의 구조는 같다. 큐 상태도 같은 SQS API(9324)로 묻는다(`watch.sh`, `queue.sh`).

| 구성 요소 | 버전 |
|---|---|
| Spring Boot | 4.1.1 |
| Spring Cloud AWS (SQS) | 4.2.0 |
| AWS SDK (SQS) | 2.47.4 |
| HikariCP | 7.0.2 |
| Hibernate | 7.4.5.Final |
| MySQL | 8.4 (Connector/J 9.7.0) |
| ElasticMQ | 1.7.1 |
| Java | 21 (Eclipse Temurin) |

## 0단계: 사전 확인 결과

- **SQS 리스너 구조는 그대로다.**
  - 원문은 Spring Cloud AWS 2.x(`org.springframework.cloud.aws`)의 `SimpleMessageListenerContainer` 코드로 설명한다. 지금의 4.x(`io.awspring.cloud`)는 새로 만들어진 코드다.
  - 4.2.0도 메시지를 처리할 스레드 풀을 "큐 하나의 동시 처리 수(`maxConcurrentMessages`, 기본 10) × 큐 수"로 만든다(`AbstractPipelineMessageListenerContainer.createTaskExecutor`). 가져온 메시지는 메시지마다 이 풀의 스레드에서 병렬로 처리한다.
  - 원문의 전제인 "가져온 메시지 수만큼 병렬로 처리한다"가 그대로 성립한다.
- **기본값끼리 맞물린다.** 리스너의 동시 처리 수 기본값(10)과 HikariCP 풀 크기 기본값(10)이 같다. 원문 공식으로 보면 메시지 1건에 커넥션이 2개 필요할 때 `10 × (2 − 1) + 1 = 11`개가 필요하다.
- **원문과 설정 이름이 다르다.**
  - 원문의 2.x는 한 번에 가져오는 메시지 수(`MaxNumberOfMessages`)가 스레드 수까지 정했다.
  - 4.x는 둘이 나뉘었다. 한 번에 가져오는 수는 `max-messages-per-poll`, 동시에 처리하는 수는 `max-concurrent-messages`다(기본값 모두 10).
- **버전 호환:** Spring Cloud AWS 4.2.0(2026-09-29)은 Spring Boot 4.0.7 기준으로 빌드됐지만, 4.1.1에서 문제없이 떴고 아래 재현도 됐다.
- **재현 확인** (Claude 검증, `results/claude-verification/stage0/`)

  | 넣은 메시지 | 동시에 처리된 메시지 | 결과 |
  |---|---|---|
  | 10건 | 최대 9건 (첫 건이 먼저 혼자 처리됨) | 10건 모두 1초 안에 완료, 타임아웃 0건 |
  | 30건 | 10건 | 6초 만에 커넥션 10개가 모두 잡히고 10개가 커넥션을 기다렸다. 타임아웃이 33초, 65초, 92초에 10건씩 났고, 그동안 완료는 1건 |

- **30건일 때 스레드 덤프:** 커넥션을 기다리던 10개 모두 같은 자리에 있었다.
  - 바깥 트랜잭션(`NoticeService.send`) 안에서 첫 커넥션을 쥐고 있었다.
  - 그 상태로 `REQUIRES_NEW` 프록시(`NoticeHistoryService$$SpringCGLIB`)에서 두 번째 커넥션을 기다렸다.

## 1단계: 재현

### 준비

```bash
./gradlew bootJar
```

```bash
docker compose up -d --build
```

### 도구

| 스크립트 | 하는 일 |
|---|---|
| `scripts/watch.sh` | 1초마다 큐, 커넥션 풀, 알림 처리 상태를 한 줄씩 출력한다. 관리 포트(8081)를 써서 장애 중에도 조회된다 |
| `scripts/publish.sh [건수]` | 알림 메시지를 한꺼번에 넣는다(기본 10건). 원문에서 각 비즈니스 로직이 알림 발송을 요청하는 부분이다 |
| `scripts/thread-dump.sh` | 스레드 덤프를 `results/thread-dump-시각.txt`에 저장하고, SQS 리스너 스레드가 무엇을 기다리는지 센다 |
| `scripts/queue.sh status\|purge` | 큐 상태를 보거나, 실험 사이에 큐를 비운다 |

`watch.sh`의 열

| 열 | 뜻 | 출처 |
|---|---|---|
| `queued` | 큐에서 처리를 기다리는 메시지 수 | SQS `ApproximateNumberOfMessages` |
| `inFlight` | 리스너가 가져가서 처리 중인 메시지 수. 처리가 끝나야 큐에서 지워진다 | SQS `ApproximateNumberOfMessagesNotVisible` |
| `active`, `idle`, `pending` | 빌려 간 커넥션, 놀고 있는 커넥션, 커넥션을 기다리는 스레드 | HikariCP |
| `timeouts` | 커넥션을 30초 안에 못 빌려 실패한 누적 횟수 | HikariCP |
| `apiCalls` | 알림톡을 실제로 보낸 누적 횟수 (가짜 Messaging API 호출) | 앱 지표 `notice.api.calls` |
| `completed` | 알림 내역까지 저장해 처리를 끝낸 누적 횟수 | 앱 지표 `notice.completed` |

**스레드 덤프:** `thread-dump.sh`는 앱 컨테이너 안에서 `jcmd 1 Thread.print -l`을 실행한다(컨테이너 안에서 java가 PID 1이다). `-l`을 붙여야 스레드가 쥔 락까지 나온다. 장애가 진행 중일 때 떠야 의미가 있다.

### 실험 1-A: 메시지가 적을 때

```bash
# 터미널 1
./scripts/watch.sh
```

```bash
# 터미널 2
./scripts/publish.sh 5
```

**관찰 포인트**
- 메시지 5건을 처리하는 데 몇 초 걸리나? `active`는 최대 몇까지 오르나?
- `apiCalls`와 `completed`는 같은가?

### 실험 1-B: 메시지가 몰릴 때

1. 터미널 1에서 상태를 화면에 보면서 파일에도 남긴다.

   ```bash
   ./scripts/watch.sh | tee "results/watch-1b-$(date +%H%M%S).txt"
   ```

2. 터미널 2에서 메시지 30건을 한꺼번에 넣는다.

   ```bash
   ./scripts/publish.sh 30
   ```

3. 10초쯤 뒤 스레드 덤프를 뜬다.

   ```bash
   ./scripts/thread-dump.sh
   ```

4. 2분쯤 지켜본 뒤, 앱 로그에서 실패를 찾아본다.

   ```bash
   docker compose logs app --no-log-prefix | grep -m3 'Connection is not available'
   ```

5. 큐를 비우고 앱을 다시 띄워 초기화한다.

   ```bash
   ./scripts/queue.sh purge
   ```

   ```bash
   docker compose restart app
   ```

**관찰 포인트**
- 메시지를 넣고 몇 초 만에 `active`, `idle`, `pending`이 어떻게 되나?
- `timeouts`는 언제, 몇 건씩 오르나?
- `apiCalls`와 `completed`는 어떻게 움직이나?
- `queued`와 `inFlight`는 어떻게 움직이나? 메시지를 더 넣지 않았는데 장애가 끝나나?
- 덤프 요약의 1)~5)는 각각 몇 개인가?

### 생각해 볼 질문 (2단계에서 증명한다)

1. 5건은 문제없는데 30건이면 멈추는 이유는? 몇 건부터 멈출까?
2. 커넥션 10개를 모두 빌려 간 동안(`active` 10) DB는 실제로 일을 하고 있을까?
3. 타임아웃은 30초마다 몇 건씩 오르나? 왜 30초이고, 왜 그 숫자일까? 첫 30초에는 타임아웃이 1건뿐이고 나머지가 완료되는 실행도 있다. 무엇이 그 차이를 만들까?
4. 메시지를 더 넣지 않았는데 장애가 끝나지 않는다면 왜일까?
5. `apiCalls`가 `completed`보다 훨씬 많다면 무슨 일이 생긴 것일까? 고객 입장에서는?

### 1단계 결과

직접 실행(2026-10-12 09:46~09:48)한 값은 **(직접)**, Claude가 검증하며 돌린 값(`results/claude-verification/stage1/`)은 **(검증)**으로 구분했다. 1-A는 화면으로만 봐서 파일이 없다. 1-B를 시작할 때 `apiCalls`, `completed`가 5, 5였던 것으로 1-A의 5건이 모두 처리된 것은 확인된다.

| 관찰 항목 | 1-A (5건) | 1-B (30건) |
|---|---|---|
| 모든 메시지를 처리하는 데 걸린 시간 | 1초 안 (검증) | 끝나지 않음. 2분 동안 30건 중 1건만 처리를 끝냄 (직접) |
| `active` / `idle` / `pending` 최대 | 1 / 9 / 0 (검증) | 발행 1초 만에 10 / 0 / 10 (직접) |
| `timeouts`가 오른 시점과 한 번에 오른 양 | 0 (검증) | 09:47:23, 09:47:54, 09:48:24에 10건씩, 약 30초 간격 (직접) |
| 2분 뒤 `apiCalls` / `completed` | 5 / 5 (직접) | 1-B 동안 41 / 1 (직접) |
| 덤프 요약 1)~5) | - | 10 / 0 / 0 / 0 / 3. 11초 간격으로 두 번 떠도 같았다 (직접) |

**1단계에서 새로 알게 된 것**
- 메시지 30건을 넣고 1초 만에 커넥션 10개가 모두 잡혔고, 10개 스레드가 커넥션을 기다렸다. 그 뒤 2분 동안 처리를 끝낸 메시지는 1건뿐이었다.
- 타임아웃이 10건 오르는 바로 그 순간 처리 중이던 메시지 10건이 큐로 돌아왔고(`queued` 19 → 29, `inFlight` 10 → 0), 2초 뒤 다시 10건을 가져가 같은 일이 되풀이됐다.
- 알림톡은 41번 나갔는데 처리를 끝낸 알림은 1건이었다.
- 큐를 비워도 이미 커넥션을 기다리던 스레드 10개는 그대로 남았다(`active` 10, `pending` 10).
- 첫 30초의 모습은 실행마다 달랐다. 직접 실행은 10건 모두 타임아웃이었고, Claude 검증 실행은 타임아웃 1건과 완료 9건이었다. (검증)
