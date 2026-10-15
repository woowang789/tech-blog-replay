package replay.fcfscoupon.issue;

import java.time.Instant;

// 온라인몰(앞단)이 1차 검증을 통과한 발급 요청을 MQ에 실어 워커에 넘기는 메시지.
// requestedAt은 1차 검증을 통과한 시각이다. 워커가 받은 시각과의 차이가 원문의 Time Gap이다
public record IssueMessage(String couponId, long userId, Instant requestedAt) {
}
