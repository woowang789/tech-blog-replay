package replay.fcfscoupon.coupon;

import java.time.Instant;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

// 미발급 기록. 사용자는 "발급 성공" 응답을 받았지만 워커의 2차 검증에서 떨어진 요청이다. 원문이 CS 문의로 알게 된 그 건들이다
@Entity
@Table(name = "issue_failures")
public class IssueFailure {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	private String couponId;

	private long userId;

	private String reason;

	private Instant failedAt;

	protected IssueFailure() {
	}

	public IssueFailure(String couponId, long userId, String reason, Instant failedAt) {
		this.couponId = couponId;
		this.userId = userId;
		this.reason = reason;
		this.failedAt = failedAt;
	}

}
