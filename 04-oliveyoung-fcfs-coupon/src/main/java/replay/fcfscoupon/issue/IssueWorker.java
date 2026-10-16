package replay.fcfscoupon.issue;

import java.time.Duration;
import java.time.Instant;

import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.amqp.support.AmqpHeaders;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.dao.DataAccessException;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.messaging.handler.annotation.Header;
import org.springframework.stereotype.Component;

import replay.fcfscoupon.coupon.Coupon;
import replay.fcfscoupon.coupon.CouponCatalog;
import replay.fcfscoupon.coupon.CouponIssue;
import replay.fcfscoupon.coupon.CouponIssueRepository;
import replay.fcfscoupon.coupon.IssueFailure;
import replay.fcfscoupon.coupon.IssueFailureRepository;
import replay.fcfscoupon.experiment.FaultInjector;

// 발급 워커. MQ에서 발급 요청을 받아 최종 확인(IssueStrategy.verify)을 하고 쿠폰을 발급한다(DB 저장).
// 원문의 기존 방식이면 여기서 GET으로 다시 읽고 INCR한다. 확인에서 떨어지면 미발급으로 기록한다.
// 4단계: DB 저장이 실패하면 ON_DB_FAILURE대로 한다. rollback은 원문처럼 수량을 되돌리고 포기한다(미발급 기록).
// retry는 예외를 그대로 던져 Spring AMQP가 메시지를 큐로 되돌리게 한다(다시 전달돼 다시 시도한다).
// IDEMPOTENT=true면 같은 사용자의 두 번째 저장을 DB의 유니크 제약이 막고, 워커는 그것을 "이미 발급됨"으로 보고 넘어간다
@Component
public class IssueWorker {

	private final CouponCatalog coupons;

	private final IssueStrategy strategy;

	private final CouponIssueRepository issues;

	private final IssueFailureRepository failures;

	private final GapStatistics gaps;

	private final WorkerCounters counters;

	private final FaultInjector faults;

	private final boolean rollbackOnDbFailure;

	public IssueWorker(CouponCatalog coupons, IssueStrategy strategy, CouponIssueRepository issues,
			IssueFailureRepository failures, GapStatistics gaps, WorkerCounters counters, FaultInjector faults,
			@Value("${replay.on-db-failure}") String onDbFailure) {
		this.coupons = coupons;
		this.strategy = strategy;
		this.issues = issues;
		this.failures = failures;
		this.gaps = gaps;
		this.counters = counters;
		this.faults = faults;
		this.rollbackOnDbFailure = switch (onDbFailure) {
			case "rollback" -> true;
			case "retry" -> false;
			default -> throw new IllegalArgumentException("모르는 on-db-failure: " + onDbFailure + " (rollback, retry 중 하나)");
		};
	}

	// concurrency: 동시에 처리하는 메시지 수. 운영의 워커 여러 대를 소비자 스레드 수로 흉내 낸다.
	// redelivered: 브로커가 이 메시지를 다시 보낸 것인지(앞 소비자가 ack하지 못했음)
	@RabbitListener(queues = "${replay.queue-name}", concurrency = "${replay.worker-concurrency}")
	public void issue(IssueMessage message, @Header(name = AmqpHeaders.REDELIVERED, required = false) Boolean redelivered) {
		boolean again = Boolean.TRUE.equals(redelivered);
		if (again) {
			counters.redelivered();
		}
		Instant received = Instant.now();
		gaps.record(Duration.between(message.requestedAt(), received));
		Coupon coupon = coupons.get(message.couponId());
		IssueStrategy.Verdict verdict = strategy.verify(coupon, message);
		if (!verdict.issue()) {
			// 사용자는 이미 "발급 성공"을 받았다. 이 기록이 원문의 미발급 건이다
			failures.save(new IssueFailure(coupon.getId(), message.userId(), message.requestedAt(), message.countSeen(),
					received, verdict.countSeen(), "2차 검증 실패: 수량 마감", Instant.now()));
			counters.handled();
			return;
		}
		try {
			faults.maybeDbError(message.userId(), again);
			issues.save(new CouponIssue(coupon.getId(), message.userId(), message.requestedAt(), message.countSeen(), received,
					verdict.countSeen(), verdict.incrResult(), Instant.now()));
		}
		catch (DataIntegrityViolationException e) {
			// 유니크 제약에 걸렸다 = 이 사용자는 이미 발급됐다(다시 전달된 메시지). 한 번 더 저장하지 않고 끝낸다
			counters.duplicatePrevented();
			counters.handled();
			return;
		}
		catch (DataAccessException e) {
			if (rollbackOnDbFailure) {
				// 원문의 처리: 선차감한 수량을 되돌리고 이 요청은 포기한다. 사용자는 이미 성공 응답을 받았다
				strategy.rollback(coupon, message);
				failures.save(new IssueFailure(coupon.getId(), message.userId(), message.requestedAt(), message.countSeen(),
						received, verdict.countSeen(), "DB 저장 실패 → 롤백", Instant.now()));
				counters.rolledBack();
				counters.handled();
				return;
			}
			throw e; // 재시도: 예외가 나가면 Spring AMQP가 메시지를 큐로 되돌리고 브로커가 다시 보낸다
		}
		faults.maybeCrashBeforeAck(message.userId(), again); // 4단계: 저장은 됐는데 ack 전에 죽음 → 다시 전달된다
		counters.handled();
	}

}
