package replay.fcfscoupon.issue;

import replay.fcfscoupon.coupon.Coupon;

// 원문의 기존 로직(0~2단계). 앞단은 GET으로 읽기만 하고, 워커가 GET으로 다시 읽어 남았으면 INCR한다. GET과 INCR이 떨어져 있다
public class OriginalStrategy implements IssueStrategy {

	private final IssueCountStore counts;

	public OriginalStrategy(IssueCountStore counts) {
		this.counts = counts;
	}

	@Override
	public Admission admit(Coupon coupon) {
		// 1차 유효성 검사: 지금까지 발급된 수가 제한 수량에 닿았으면 마감 (GET)
		long seen = counts.get(coupon.getId());
		return new Admission(seen < coupon.getIssueLimit(), seen, 0);
	}

	@Override
	public Verdict verify(Coupon coupon, IssueMessage message) {
		// 2차 유효성 검사: 1차 검증 뒤 지금까지 다른 요청이 수량을 다 썼으면 발급하지 못한다 (GET)
		long seen = counts.get(coupon.getId());
		if (seen >= coupon.getIssueLimit()) {
			return new Verdict(false, seen, -1);
		}
		long incremented = counts.increment(coupon.getId(), coupon.getEndsAt()); // INCR (GET과 별도 명령)
		return new Verdict(true, seen, incremented);
	}

}
