package replay.fcfscoupon.issue;

import java.time.Instant;

// 온라인몰(앞단)이 1차 검증을 통과한 발급 요청을 MQ에 실어 워커에 넘기는 메시지.
// requestedAt은 1차 검증을 통과한 시각, countSeen은 그때 읽은 수량(읽지 않는 방식이면 -1),
// position은 앞단이 선차감했을 때 INCR이 돌려준 순번(선차감하지 않는 방식이면 0. 3단계).
// 워커가 받은 시각과 requestedAt의 차이가 원문의 Time Gap이다
public record IssueMessage(String couponId, long userId, Instant requestedAt, long countSeen, long position) {
}
