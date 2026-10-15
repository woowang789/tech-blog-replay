package replay.fcfscoupon.issue;

import java.time.Instant;

import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import replay.fcfscoupon.coupon.Coupon;
import replay.fcfscoupon.coupon.CouponCatalog;

// 온라인몰(앞단)의 발급 요청 처리. 원문의 기존 로직이다:
// Redis에서 수량을 읽어 1차 검증하고, 통과하면 MQ에 발행한 뒤 사용자에게 바로 "발급 성공"으로 응답한다.
// 수량을 올리는 것(INCR)은 워커의 일이라 여기서는 읽기만 한다
@Service
public class IssueService {

	private final CouponCatalog coupons;

	private final IssueCountStore counts;

	private final RabbitTemplate rabbit;

	private final ResponseCounters responses;

	private final String queueName;

	public IssueService(CouponCatalog coupons, IssueCountStore counts, RabbitTemplate rabbit, ResponseCounters responses,
			@Value("${replay.queue-name}") String queueName) {
		this.coupons = coupons;
		this.counts = counts;
		this.rabbit = rabbit;
		this.responses = responses;
		this.queueName = queueName;
	}

	public IssueResult request(String couponId, long userId) {
		Coupon coupon = coupons.get(couponId);
		IssueResult result;
		// 1차 유효성 검사: 지금까지 발급된 수가 제한 수량에 닿았으면 마감 (GET)
		if (counts.get(couponId) >= coupon.getIssueLimit()) {
			result = IssueResult.SOLD_OUT;
		}
		else {
			// 통과하면 실제 발급은 워커에 맡기고(MQ 발행) 사용자에게는 성공으로 응답한다
			rabbit.convertAndSend(queueName, new IssueMessage(couponId, userId, Instant.now()));
			result = IssueResult.SUCCESS;
		}
		responses.count(result);
		return result;
	}

}
