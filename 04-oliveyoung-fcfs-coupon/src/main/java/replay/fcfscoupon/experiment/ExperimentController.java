package replay.fcfscoupon.experiment;

import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;

import org.springframework.amqp.core.AmqpAdmin;
import org.springframework.amqp.core.QueueInformation;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import replay.fcfscoupon.coupon.Coupon;
import replay.fcfscoupon.coupon.CouponCatalog;
import replay.fcfscoupon.coupon.CouponIssue;
import replay.fcfscoupon.coupon.CouponIssueRepository;
import replay.fcfscoupon.coupon.CouponRepository;
import replay.fcfscoupon.coupon.IssueFailure;
import replay.fcfscoupon.coupon.IssueFailureRepository;
import replay.fcfscoupon.issue.GapStatistics;
import replay.fcfscoupon.issue.IssueCountStore;
import replay.fcfscoupon.issue.ResponseCounters;
import replay.fcfscoupon.issue.WorkerCounters;

// 실험용: 실험 전에 모든 상태를 비우고 쿠폰을 하나 만들며(reset), 실험 뒤에 결과를 한눈에 모은다(summary, records)
@RestController
@RequestMapping("/experiments")
class ExperimentController {

	private final CouponRepository coupons;

	private final CouponCatalog catalog;

	private final CouponIssueRepository issues;

	private final IssueFailureRepository failures;

	private final IssueCountStore counts;

	private final ResponseCounters responses;

	private final GapStatistics gaps;

	private final WorkerCounters handled;

	private final FaultInjector faults;

	private final AmqpAdmin amqp;

	private final String queueName;

	ExperimentController(CouponRepository coupons, CouponCatalog catalog, CouponIssueRepository issues,
			IssueFailureRepository failures, IssueCountStore counts, ResponseCounters responses, GapStatistics gaps,
			WorkerCounters handled, FaultInjector faults, AmqpAdmin amqp, @Value("${replay.queue-name}") String queueName) {
		this.coupons = coupons;
		this.catalog = catalog;
		this.issues = issues;
		this.failures = failures;
		this.counts = counts;
		this.responses = responses;
		this.gaps = gaps;
		this.handled = handled;
		this.faults = faults;
		this.amqp = amqp;
		this.queueName = queueName;
	}

	// 큐, DB, Redis 수량, 집계를 모두 비우고 제한 수량이 limit인 쿠폰을 만든다. 앞 실험이 남긴 것이 다음 결과에 섞이지 않게 한다
	@PostMapping("/reset")
	Coupon reset(@RequestParam(defaultValue = "C001") String couponId, @RequestParam(defaultValue = "100") int limit) {
		amqp.purgeQueue(queueName);
		issues.deleteAllInBatch();
		failures.deleteAllInBatch();
		counts.delete(couponId);
		responses.reset();
		gaps.reset();
		handled.reset();
		faults.reset();
		Coupon coupon = coupons.save(new Coupon(couponId, limit, Instant.now().plus(Duration.ofDays(1))));
		catalog.refresh(coupon);
		return coupon;
	}

	@GetMapping("/summary")
	Summary summary(@RequestParam(defaultValue = "C001") String couponId) {
		Coupon coupon = catalog.get(couponId);
		QueueInformation queue = amqp.getQueueInfo(queueName);
		long issued = issues.countByCouponId(couponId);
		long distinctUsers = issues.countDistinctUsers(couponId);
		return new Summary(couponId, coupon.getIssueLimit(), counts.get(couponId), counts.getRequests(couponId),
				responses.success(), responses.soldOut(), issued, distinctUsers, issued - distinctUsers,
				failures.countByCouponId(couponId), Math.max(0, distinctUsers - coupon.getIssueLimit()),
				responses.success() - distinctUsers, queue == null ? -1 : queue.getMessageCount(),
				queue == null ? -1 : queue.getConsumerCount(), gaps.snapshot(),
				new Faults(faults.fault().name(), faults.injectedCount(), handled.redeliveredCount(), handled.rolledBackCount(),
						handled.duplicatePreventedCount()));
	}

	// 4단계 정합성 보정: 큐가 비어 처리 중인 요청이 없을 때, 어긋난 countReq를 count에 맞춘다. 앞뒤 값을 돌려준다
	@PostMapping("/reconcile")
	Reconcile reconcile(@RequestParam(defaultValue = "C001") String couponId) {
		QueueInformation queue = amqp.getQueueInfo(queueName);
		long count = counts.get(couponId);
		long before = counts.getRequests(couponId);
		boolean applied = queue != null && queue.getMessageCount() == 0 && before != count;
		if (applied) {
			counts.setRequests(couponId, count);
		}
		return new Reconcile(count, before, counts.getRequests(couponId), applied);
	}

	record Reconcile(long count, long countReqBefore, long countReqAfter, boolean applied) {
	}

	// 실험 중 0.1초마다 읽어도 가벼운 진행 상태(1단계 실행기가 쓴다). DB는 세지 않는다. 발급 누계는 Redis 수량으로 본다
	@GetMapping("/progress")
	Progress progress(@RequestParam(defaultValue = "C001") String couponId) {
		QueueInformation queue = amqp.getQueueInfo(queueName);
		return new Progress(responses.success(), responses.soldOut(), counts.get(couponId), handled.handledCount(),
				queue == null ? -1 : queue.getMessageCount());
	}

	// handled: 워커가 처리를 끝낸 수(발급 + 미발급). queued: 큐에서 기다리는 수(워커가 미리 가져간 메시지는 뺀 값)
	record Progress(long successResponses, long soldOutResponses, long redisCount, long handled, long queued) {
	}

	// 2단계: 요청마다 남긴 기록(발급·미발급 모두). 1차 검증 시각과 그때 본 수량, 2차 검증 시각과 그때 본 수량, INCR 결과.
	// 시각은 epoch 마이크로초다(앱 시계 기준)
	@GetMapping("/records")
	List<IssueRecord> records(@RequestParam(defaultValue = "C001") String couponId) {
		List<IssueRecord> records = new ArrayList<>();
		for (CouponIssue issue : issues.findByCouponId(couponId)) {
			records.add(new IssueRecord(issue.getUserId(), "ISSUED", micros(issue.getFirstCheckAt()), issue.getFirstCheckCount(),
					micros(issue.getSecondCheckAt()), issue.getSecondCheckCount(), issue.getIncrResult()));
		}
		for (IssueFailure failure : failures.findByCouponId(couponId)) {
			records.add(new IssueRecord(failure.getUserId(), "UNISSUED", micros(failure.getFirstCheckAt()),
					failure.getFirstCheckCount(), micros(failure.getSecondCheckAt()), failure.getSecondCheckCount(), null));
		}
		return records;
	}

	private static long micros(Instant instant) {
		return instant.getEpochSecond() * 1_000_000 + instant.getNano() / 1_000;
	}

	record IssueRecord(long userId, String result, long firstCheckAt, long firstCheckCount, long secondCheckAt,
			long secondCheckCount, Long incrResult) {
	}

	// redisCount: 수량 키(count), redisRequestCount: 요청 수량 키(countReq, 시도 3에서만 쓴다), successResponses: "발급 성공" 응답 수,
	// issued: 발급 기록 행 수(DB), issuedUsers: 발급 기록이 있는 사용자 수, duplicateIssues: 같은 사용자에게 두 번 이상 저장된 수(4단계),
	// unissued: 워커가 미발급으로 기록한 수(2차 검증 실패, 롤백), overIssued: 제한 수량을 넘겨 발급한 사용자 수,
	// brokenPromises: 성공 응답을 받았지만 발급 기록이 없는 사용자 수(= 약속을 어긴 수), queued: 큐에 남은 메시지 수(0이어야 집계가 끝난 것이다),
	// faults: 주입한 실패 수, 다시 전달된 메시지 수, 원문 방식으로 롤백한 수, 유니크 제약이 막은 중복 수
	record Summary(String couponId, int issueLimit, long redisCount, long redisRequestCount, long successResponses,
			long soldOutResponses, long issued, long issuedUsers, long duplicateIssues, long unissued, long overIssued,
			long brokenPromises, long queued, long consumers, GapStatistics.Snapshot gapMs, Faults faults) {
	}

	record Faults(String fault, long injected, long redelivered, long rolledBack, long duplicatePrevented) {
	}

}
