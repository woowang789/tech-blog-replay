package replay.fcfscoupon.coupon;

import org.springframework.data.jpa.repository.JpaRepository;

public interface CouponIssueRepository extends JpaRepository<CouponIssue, Long> {

	long countByCouponId(String couponId);

}
