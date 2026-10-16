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

// 발급 워커. MQ에서 발급 요청을 받아 최종 확인(IssueStrategy.verify)을 하고 쿠폰을 발급한다(DB 저장).
// 원문의 기존 방식이면 여기서 GET으로 다시 읽고 INCR한다. 확인에서 떨어지면 미발급으로 기록한다
@Component
public class IssueWorker {

	private final CouponCatalog coupons;

	private final IssueStrategy strategy;

	private final CouponIssueRepository issues;

	private final IssueFailureRepository failures;

	private final GapStatistics gaps;

	private final WorkerCounters handled;

	public IssueWorker(CouponCatalog coupons, IssueStrategy strategy, CouponIssueRepository issues,
			IssueFailureRepository failures, GapStatistics gaps, WorkerCounters handled) {
		this.coupons = coupons;
		this.strategy = strategy;
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
		IssueStrategy.Verdict verdict = strategy.verify(coupon, message);
		if (!verdict.issue()) {
			// 사용자는 이미 "발급 성공"을 받았다. 이 기록이 원문의 미발급 건이다
			failures.save(new IssueFailure(coupon.getId(), message.userId(), message.requestedAt(), message.countSeen(),
					received, verdict.countSeen(), "2차 검증 실패: 수량 마감", Instant.now()));
			handled.handled();
			return;
		}
		issues.save(new CouponIssue(coupon.getId(), message.userId(), message.requestedAt(), message.countSeen(), received,
				verdict.countSeen(), verdict.incrResult(), Instant.now()));
		handled.handled();
	}

}
