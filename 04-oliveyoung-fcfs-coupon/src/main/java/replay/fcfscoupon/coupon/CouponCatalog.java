package replay.fcfscoupon.coupon;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

import org.springframework.stereotype.Component;

// 쿠폰 정보(제한 수량, 유효 기간)를 메모리에 들고 있다. 발급 요청마다 DB를 읽으면 그 비용이 Redis 쪽 차이를 덮어서,
// 원문처럼 요청 경로에서는 DB를 조회하지 않는다. 실험을 초기화할 때 다시 채운다
@Component
public class CouponCatalog {

	private final CouponRepository repository;

	private final Map<String, Coupon> coupons = new ConcurrentHashMap<>();

	public CouponCatalog(CouponRepository repository) {
		this.repository = repository;
	}

	public Coupon get(String couponId) {
		return coupons.computeIfAbsent(couponId, id -> repository.findById(id)
				.orElseThrow(() -> new IllegalArgumentException("없는 쿠폰: " + id)));
	}

	public void refresh(Coupon coupon) {
		coupons.put(coupon.getId(), coupon);
	}

}
