package replay.fcfscoupon.issue;

import replay.fcfscoupon.coupon.Coupon;

// 앞단과 워커가 수량을 다루는 방법. 원문의 기존 로직(original)과 세 시도(precharge, lua, double-counter)를 바꿔 끼운다(3단계).
// 어느 방식이든 앞단은 받아들인 요청만 MQ에 싣고 사용자에게 "발급 성공"으로 응답하며, 워커가 DB에 발급을 남긴다
public interface IssueStrategy {

	// 앞단: 요청을 받아들일지 정한다. countSeen은 그때 읽은 수량(읽지 않는 방식이면 -1), position은 선차감한 순번(선차감하지 않으면 0)
	Admission admit(Coupon coupon, long userId);

	// 워커: 발급해도 되는지 최종 확인한다. countSeen은 그때 본 수량, incrResult는 INCR이 돌려준 값(INCR하지 않으면 -1)
	Verdict verify(Coupon coupon, IssueMessage message);

	// 워커: 발급을 확정했다가 DB 저장이 실패했을 때 수량을 되돌린다(원문의 "DB 처리 실패 시 롤백". 4단계)
	void rollback(Coupon coupon, IssueMessage message);

	record Admission(boolean admitted, long countSeen, long position) {
	}

	record Verdict(boolean issue, long countSeen, long incrResult) {
	}

}
