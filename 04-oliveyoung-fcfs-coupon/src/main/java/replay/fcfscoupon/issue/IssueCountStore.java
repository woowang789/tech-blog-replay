package replay.fcfscoupon.issue;

import java.time.Instant;
import java.util.List;

import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.data.redis.core.script.RedisScript;
import org.springframework.stereotype.Component;

// Redis에 둔 쿠폰별 수량. 원문의 키 이름을 따른다: coupon:{couponId}:count(실제 발급 수), coupon:{couponId}:countReq(발급 요청 수, 시도 3).
// get()은 GET, increment()는 INCR 한 번씩이다. 둘을 이어 부르면 그 사이에 다른 요청이 끼어들 수 있다(원문의 "원자성 부재")
@Component
public class IssueCountStore {

	// 원문의 시도 2 스크립트 그대로. KEYS[1] = 수량 키, ARGV[1] = 제한 수량, ARGV[2] = 만료 시각(epoch 초).
	// GET → 비교 → INCR(키가 없으면 SET 1 + EXPIREAT)을 Redis가 한 번에 실행한다. true면 받아들인 것이다
	static final String ADMIT_SCRIPT = """
			local current = redis.call('GET', KEYS[1])
			if current then
			    local num = tonumber(current)
			    if num and num < tonumber(ARGV[1]) then
			        redis.call('INCR', KEYS[1])
			        return true
			    else
			        return false
			    end
			else
			    redis.call('SET', KEYS[1], 1)
			    redis.call('EXPIREAT', KEYS[1], tonumber(ARGV[2]))
			    return true
			end
			""";

	private final StringRedisTemplate redis;

	private final RedisScript<Boolean> admitScript = new DefaultRedisScript<>(ADMIT_SCRIPT, Boolean.class);

	public IssueCountStore(StringRedisTemplate redis) {
		this.redis = redis;
	}

	// 지금까지 발급된 수. 키가 없으면(첫 발급 전) 0
	public long get(String couponId) {
		return read(key(couponId));
	}

	// 발급 수를 1 올리고 올린 뒤의 값을 돌려준다. 처음 만든 키면 원문처럼 쿠폰 유효 기간까지의 TTL을 건다
	public long increment(String couponId, Instant endsAt) {
		return incrementWithTtl(key(couponId), endsAt);
	}

	// 발급 수를 1 되돌린다(시도 1·3의 롤백)
	public long decrement(String couponId) {
		return redis.opsForValue().decrement(key(couponId));
	}

	// 시도 2: 스크립트 한 번으로 읽고·비교하고·올린다. Spring Data Redis는 EVALSHA로 보내고, 스크립트가 없으면 EVAL로 올린다
	public boolean admitAtomically(String couponId, int limit, Instant endsAt) {
		Boolean admitted = redis.execute(admitScript, List.of(key(couponId)), String.valueOf(limit),
				String.valueOf(endsAt.getEpochSecond()));
		return Boolean.TRUE.equals(admitted);
	}

	// 시도 3: 발급 요청 수(countReq)
	public long getRequests(String couponId) {
		return read(requestKey(couponId));
	}

	public long incrementRequests(String couponId, Instant endsAt) {
		return incrementWithTtl(requestKey(couponId), endsAt);
	}

	public long decrementRequests(String couponId) {
		return redis.opsForValue().decrement(requestKey(couponId));
	}

	public void delete(String couponId) {
		redis.delete(List.of(key(couponId), requestKey(couponId)));
	}

	private long read(String key) {
		String value = redis.opsForValue().get(key);
		return value == null ? 0 : Long.parseLong(value);
	}

	private long incrementWithTtl(String key, Instant endsAt) {
		Long count = redis.opsForValue().increment(key);
		if (count == 1) {
			redis.expireAt(key, endsAt);
		}
		return count;
	}

	static String key(String couponId) {
		return "coupon:" + couponId + ":count";
	}

	static String requestKey(String couponId) {
		return "coupon:" + couponId + ":countReq";
	}

}
