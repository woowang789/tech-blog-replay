package replay.fcfscoupon.coupon;

import java.time.Instant;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

// 발급 내역. 워커가 2차 검증을 통과한 요청만 여기에 남는다. 이 행 수가 실제로 발급된 수다.
// 2단계부터 요청이 거쳐 온 길을 함께 남긴다: 1차 검증 시각과 그때 본 수량, 2차 검증 시각과 그때 본 수량, INCR이 돌려준 값
@Entity
@Table(name = "coupon_issues")
public class CouponIssue {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	private String couponId;

	private long userId;

	private Instant firstCheckAt;

	private long firstCheckCount;

	private Instant secondCheckAt;

	private long secondCheckCount;

	private long incrResult;

	private Instant issuedAt;

	protected CouponIssue() {
	}

	public CouponIssue(String couponId, long userId, Instant firstCheckAt, long firstCheckCount, Instant secondCheckAt,
			long secondCheckCount, long incrResult, Instant issuedAt) {
		this.couponId = couponId;
		this.userId = userId;
		this.firstCheckAt = firstCheckAt;
		this.firstCheckCount = firstCheckCount;
		this.secondCheckAt = secondCheckAt;
		this.secondCheckCount = secondCheckCount;
		this.incrResult = incrResult;
		this.issuedAt = issuedAt;
	}

	public long getUserId() {
		return userId;
	}

	public Instant getFirstCheckAt() {
		return firstCheckAt;
	}

	public long getFirstCheckCount() {
		return firstCheckCount;
	}

	public Instant getSecondCheckAt() {
		return secondCheckAt;
	}

	public long getSecondCheckCount() {
		return secondCheckCount;
	}

	public long getIncrResult() {
		return incrResult;
	}

}
