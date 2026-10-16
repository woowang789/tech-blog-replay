package replay.fcfscoupon.coupon;

import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;

public interface CouponIssueRepository extends JpaRepository<CouponIssue, Long> {

	long countByCouponId(String couponId);

	List<CouponIssue> findByCouponId(String couponId);

}
