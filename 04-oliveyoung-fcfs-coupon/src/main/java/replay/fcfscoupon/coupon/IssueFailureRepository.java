package replay.fcfscoupon.coupon;

import org.springframework.data.jpa.repository.JpaRepository;

public interface IssueFailureRepository extends JpaRepository<IssueFailure, Long> {

	long countByCouponId(String couponId);

}
