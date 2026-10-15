package replay.fcfscoupon.coupon;

import java.time.Instant;

import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

// 선착순 쿠폰. 원문처럼 발급 제한 수량과 유효 기간(Redis 수량 키 TTL의 기준)을 가진다
@Entity
@Table(name = "coupons")
public class Coupon {

	@Id
	private String id;

	private int issueLimit;

	private Instant endsAt;

	protected Coupon() {
	}

	public Coupon(String id, int issueLimit, Instant endsAt) {
		this.id = id;
		this.issueLimit = issueLimit;
		this.endsAt = endsAt;
	}

	public String getId() {
		return id;
	}

	public int getIssueLimit() {
		return issueLimit;
	}

	public Instant getEndsAt() {
		return endsAt;
	}

}
