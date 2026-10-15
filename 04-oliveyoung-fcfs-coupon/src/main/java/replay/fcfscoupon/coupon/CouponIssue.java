package replay.fcfscoupon.coupon;

import java.time.Instant;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

// 발급 내역. 워커가 2차 검증을 통과한 요청만 여기에 남는다. 이 행 수가 실제로 발급된 수다
@Entity
@Table(name = "coupon_issues")
public class CouponIssue {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	private String couponId;

	private long userId;

	private Instant issuedAt;

	protected CouponIssue() {
	}

	public CouponIssue(String couponId, long userId, Instant issuedAt) {
		this.couponId = couponId;
		this.userId = userId;
		this.issuedAt = issuedAt;
	}

}
