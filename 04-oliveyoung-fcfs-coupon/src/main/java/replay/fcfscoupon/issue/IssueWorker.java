package replay.fcfscoupon.issue;

import java.time.Duration;
import java.time.Instant;

import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

import replay.fcfscoupon.coupon.Coupon;
import replay.fcfscoupon.coupon.CouponCatalog;
import replay.fcfscoupon.coupon.CouponIssue;
import replay.fcfscoupon.coupon.CouponIssueRepository;
import replay.fcfscoupon.coupon.IssueFailure;
import replay.fcfscoupon.coupon.IssueFailureRepository;

// 발급 워커. MQ에서 발급 요청을 받아 2차 검증을 하고 쿠폰을 최종 발급한다(DB 저장).
// 원문의 "문제가 되는 코드 패턴" 그대로, 수량을 읽어(GET) 남았으면 올린다(INCR). 두 명령이 떨어져 있다
@Component
public class IssueWorker {

	private final CouponCatalog coupons;

	private final IssueCountStore counts;

	private final CouponIssueRepository issues;

	private final IssueFailureRepository failures;

	private final GapStatistics gaps;

	private final WorkerCounters handled;

	public IssueWorker(CouponCatalog coupons, IssueCountStore counts, CouponIssueRepository issues,
			IssueFailureRepository failures, GapStatistics gaps, WorkerCounters handled) {
		this.coupons = coupons;
		this.counts = counts;
		this.issues = issues;
		this.failures = failures;
		this.gaps = gaps;
		this.handled = handled;
	}

	// concurrency: 동시에 처리하는 메시지 수. 운영의 워커 여러 대를 소비자 스레드 수로 흉내 낸다
	@RabbitListener(queues = "${replay.queue-name}", concurrency = "${replay.worker-concurrency}")
	public void issue(IssueMessage message) {
		Instant received = Instant.now();
		gaps.record(Duration.between(message.requestedAt(), received));
		Coupon coupon = coupons.get(message.couponId());
		// 2차 유효성 검사: 1차 검증 뒤 지금까지 다른 요청이 수량을 다 썼으면 발급하지 못한다 (GET)
		if (counts.get(coupon.getId()) >= coupon.getIssueLimit()) {
			// 사용자는 이미 "발급 성공"을 받았다. 이 기록이 원문의 미발급 건이다
			failures.save(new IssueFailure(coupon.getId(), message.userId(), "2차 검증 실패: 수량 마감", received));
			handled.handled();
			return;
		}
		counts.increment(coupon.getId(), coupon.getEndsAt()); // INCR (GET과 별도 명령)
		issues.save(new CouponIssue(coupon.getId(), message.userId(), Instant.now()));
		handled.handled();
	}

}
