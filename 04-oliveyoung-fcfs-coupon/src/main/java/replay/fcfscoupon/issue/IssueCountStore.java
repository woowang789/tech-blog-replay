package replay.fcfscoupon.issue;

import java.time.Instant;

import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

// Redis에 둔 쿠폰별 발급 수량. 원문의 키 이름(coupon:{couponId}:count)을 따른다.
// get()은 GET, increment()는 INCR 한 번씩이다. 둘을 이어 부르면 그 사이에 다른 요청이 끼어들 수 있다(원문의 "원자성 부재")
@Component
public class IssueCountStore {

	private final StringRedisTemplate redis;

	public IssueCountStore(StringRedisTemplate redis) {
		this.redis = redis;
	}

	// 지금까지 발급된 수. 키가 없으면(첫 발급 전) 0
	public long get(String couponId) {
		String value = redis.opsForValue().get(key(couponId));
		return value == null ? 0 : Long.parseLong(value);
	}

	// 발급 수를 1 올리고 올린 뒤의 값을 돌려준다. 처음 만든 키면 원문처럼 쿠폰 유효 기간까지의 TTL을 건다
	public long increment(String couponId, Instant endsAt) {
		Long count = redis.opsForValue().increment(key(couponId));
		if (count == 1) {
			redis.expireAt(key(couponId), endsAt);
		}
		return count;
	}

	public void delete(String couponId) {
		redis.delete(key(couponId));
	}

	static String key(String couponId) {
		return "coupon:" + couponId + ":count";
	}

}
