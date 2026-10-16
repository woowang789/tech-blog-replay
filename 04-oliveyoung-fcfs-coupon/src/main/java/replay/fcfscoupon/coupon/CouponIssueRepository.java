package replay.fcfscoupon.coupon;

import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface CouponIssueRepository extends JpaRepository<CouponIssue, Long> {

	long countByCouponId(String couponId);

	List<CouponIssue> findByCouponId(String couponId);

	// 발급 기록이 있는 사용자 수. 같은 사용자가 두 번 저장됐으면(중복 발급) 행 수보다 작다
	@Query("select count(distinct i.userId) from CouponIssue i where i.couponId = :couponId")
	long countDistinctUsers(@Param("couponId") String couponId);

}
