package replay.fcfscoupon.issue;

import replay.fcfscoupon.coupon.Coupon;

// 원문의 시도 2: Lua 스크립트. GET·비교·INCR(키가 없으면 SET 1 + EXPIREAT)을 스크립트 하나로 묶어 Redis가 원자적으로 실행한다.
// 스크립트는 원문 그대로다(IssueCountStore.ADMIT_SCRIPT). 워커는 수량을 다시 보지 않고 발급만 한다.
// 원문은 미발급·과발급이 0이 됐지만 성능이 약 21% 떨어져 기각했다
public class LuaStrategy implements IssueStrategy {

	private final IssueCountStore counts;

	public LuaStrategy(IssueCountStore counts) {
		this.counts = counts;
	}

	@Override
	public Admission admit(Coupon coupon, long userId) {
		boolean admitted = counts.admitAtomically(coupon.getId(), coupon.getIssueLimit(), coupon.getEndsAt());
		return new Admission(admitted, -1, 0);
	}

	@Override
	public Verdict verify(Coupon coupon, IssueMessage message) {
		return new Verdict(true, -1, -1);
	}

	@Override
	public void rollback(Coupon coupon, IssueMessage message) {
		counts.decrement(coupon.getId()); // 스크립트가 올린 수량을 되돌린다
	}

}
