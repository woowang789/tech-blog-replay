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
| 1. 재현 | 메시지가 몰리면 커넥션 풀이 멈추고 30초마다 한꺼번에 실패하는 장애 | |
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

**ElasticMQ를 쓴 이유:** SQS API를 그대로 흉내 내는 로컬 서버라 Spring Cloud AWS가 실제 SQS처럼 쓴다. 메시지를 몇 건씩 가져와 몇 개의 스레드로 처리할지는 Spring Cloud AWS 쪽 리스너 컨테이너가 정하므로, 로컬 서버를 써도 이 장애의 구조는 같다. 9325 포트에 큐 상태를 보는 웹 화면이 있다.

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

