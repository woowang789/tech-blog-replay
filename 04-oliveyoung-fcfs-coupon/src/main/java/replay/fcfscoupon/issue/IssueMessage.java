package replay.fcfscoupon.issue;

import java.time.Instant;

// 온라인몰(앞단)이 1차 검증을 통과한 발급 요청을 MQ에 실어 워커에 넘기는 메시지.
// requestedAt은 1차 검증을 통과한 시각, countSeen은 그때 Redis에서 읽은 발급 수량이다(2단계: 1차 검증이 무엇을 보고 통과시켰는지 남긴다).
// 워커가 받은 시각과 requestedAt의 차이가 원문의 Time Gap이다
public record IssueMessage(String couponId, long userId, Instant requestedAt, long countSeen) {
}
