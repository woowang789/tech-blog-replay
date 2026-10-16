package replay.fcfscoupon.issue;

import replay.fcfscoupon.coupon.Coupon;
import replay.fcfscoupon.experiment.FaultInjector;

// 원문의 시도 3: 이중 카운터(원문의 최종 선택, 시도 1의 선차감과 조합).
// 요청 수량 키(coupon:{id}:countReq)를 먼저 INCR하고 그 결과로 받아들일지 정한다. INCR은 원자적이고 올린 뒤의 값을 돌려주니
// 동시 요청이 같은 값을 보는 일이 없다. 통과한 요청만 실제 발급 수량 키(coupon:{id}:count)를 INCR한다(선차감).
// 원문의 흐름도는 이미지라 세부는 복원했다: 마감된 요청은 countReq를 되돌려(DECR) 두 키가 평소에는 같은 값을 가리키게 한다.
// 원문이 "count와 countReq의 차이를 모니터링해 알람"하는 것과 맞춘 것이다. 워커는 순번이 제한을 넘지 않았는지만 확인한다(넘을 일이 없다).
// 4단계: countReq를 올린 뒤 count를 올리기 전에 실패하면(FAULT=front-crash) 두 키가 어긋난다. COMPENSATE=true면 예외를 잡아 countReq를 되돌린다
public class DoubleCounterStrategy implements IssueStrategy {

	private final IssueCountStore counts;

	private final FaultInjector faults;

	private final boolean compensate;

	public DoubleCounterStrategy(IssueCountStore counts, FaultInjector faults, boolean compensate) {
		this.counts = counts;
		this.faults = faults;
		this.compensate = compensate;
	}

	@Override
	public Admission admit(Coupon coupon, long userId) {
		long requested = counts.incrementRequests(coupon.getId(), coupon.getEndsAt()); // INCR countReq
		if (requested > coupon.getIssueLimit()) {
			counts.decrementRequests(coupon.getId());
			return new Admission(false, requested, 0);
		}
		long position;
		try {
			faults.maybeFrontCrash(userId); // 4단계: 여기서 죽으면 countReq만 올라 있다
			position = counts.increment(coupon.getId(), coupon.getEndsAt()); // INCR count (선차감)
		}
		catch (RuntimeException e) {
			if (compensate) {
				counts.decrementRequests(coupon.getId()); // 보상: 예외라면 되돌릴 수 있다. 프로세스가 죽은 것이라면 이 코드도 돌지 않는다
			}
			throw e;
		}
		return new Admission(true, requested, position);
	}

	@Override
	public Verdict verify(Coupon coupon, IssueMessage message) {
		if (message.position() > coupon.getIssueLimit()) {
			rollback(coupon, message);
			return new Verdict(false, message.position(), -1);
		}
		return new Verdict(true, message.position(), message.position());
	}

	@Override
	public void rollback(Coupon coupon, IssueMessage message) {
		counts.decrement(coupon.getId());
		counts.decrementRequests(coupon.getId());
	}

}
