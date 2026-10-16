package replay.fcfscoupon.coupon;

import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;

public interface IssueFailureRepository extends JpaRepository<IssueFailure, Long> {

	long countByCouponId(String couponId);

	List<IssueFailure> findByCouponId(String couponId);

}
