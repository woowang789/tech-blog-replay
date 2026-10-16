package replay.fcfscoupon.issue;

import java.time.Instant;

import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import replay.fcfscoupon.coupon.Coupon;
import replay.fcfscoupon.coupon.CouponCatalog;

// 온라인몰(앞단)의 발급 요청 처리. 수량을 보고 받아들일지는 IssueStrategy(ISSUE_MODE)가 정한다.
// 받아들이면 실제 발급은 워커에 맡기고(MQ 발행) 사용자에게 바로 "발급 성공"으로 응답한다
@Service
public class IssueService {

	private final CouponCatalog coupons;

	private final IssueStrategy strategy;

	private final RabbitTemplate rabbit;

	private final ResponseCounters responses;

	private final String queueName;

	public IssueService(CouponCatalog coupons, IssueStrategy strategy, RabbitTemplate rabbit, ResponseCounters responses,
			@Value("${replay.queue-name}") String queueName) {
		this.coupons = coupons;
		this.strategy = strategy;
		this.rabbit = rabbit;
		this.responses = responses;
		this.queueName = queueName;
	}

	public IssueResult request(String couponId, long userId) {
		Coupon coupon = coupons.get(couponId);
		IssueStrategy.Admission admission = strategy.admit(coupon);
		IssueResult result;
		if (!admission.admitted()) {
			result = IssueResult.SOLD_OUT;
		}
		else {
			rabbit.convertAndSend(queueName,
					new IssueMessage(couponId, userId, Instant.now(), admission.countSeen(), admission.position()));
			result = IssueResult.SUCCESS;
		}
		responses.count(result);
		return result;
	}

}
