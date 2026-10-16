package replay.fcfscoupon.issue;

import replay.fcfscoupon.coupon.Coupon;

// 원문의 시도 1: 발급 수량 선차감. INCR을 워커에서 앞단으로 옮겨, 1차 검증(GET)과 수량 반영(INCR) 사이에 끼어 있던 MQ 전송 시간을 없앤다.
// 하지만 앞단의 GET과 INCR은 여전히 별도 명령이다.
// 원문에 코드가 없어 워커의 2차 검증은 "선차감한 순번(INCR 결과)이 제한을 넘었는가"로 복원했다. 넘었으면 미발급으로 기록하고
// 선차감한 수량을 되돌린다(DECR). 원문이 적은 "DB 처리 실패 시 롤백"도 같은 DECR이다(이 실험에서는 DB 실패를 만들지 않는다)
public class PrechargeStrategy implements IssueStrategy {

	private final IssueCountStore counts;

	public PrechargeStrategy(IssueCountStore counts) {
		this.counts = counts;
	}

	@Override
	public Admission admit(Coupon coupon, long userId) {
		long seen = counts.get(coupon.getId()); // GET
		if (seen >= coupon.getIssueLimit()) {
			return new Admission(false, seen, 0);
		}
		long position = counts.increment(coupon.getId(), coupon.getEndsAt()); // INCR (선차감. GET과 별도 명령)
		return new Admission(true, seen, position);
	}

	@Override
	public Verdict verify(Coupon coupon, IssueMessage message) {
		if (message.position() > coupon.getIssueLimit()) {
			counts.decrement(coupon.getId()); // 롤백
			return new Verdict(false, message.position(), -1);
		}
		return new Verdict(true, message.position(), message.position());
	}

	@Override
	public void rollback(Coupon coupon, IssueMessage message) {
		counts.decrement(coupon.getId()); // 앞단이 선차감한 수량을 되돌린다
	}

}
