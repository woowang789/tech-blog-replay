package replay.cacheevict.experiment;

import java.nio.charset.StandardCharsets;

import org.springframework.data.redis.cache.RedisCache;
import org.springframework.data.redis.cache.RedisCacheConfiguration;
import org.springframework.data.redis.cache.RedisCacheManager;
import org.springframework.data.redis.connection.RedisConnection;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.util.ByteUtils;
import org.springframework.stereotype.Component;

import replay.cacheevict.product.Product;

// 실험용: products 캐시에 상품 count개를 한꺼번에 넣는다.
// @Cacheable이 넣는 것과 같은 키(products::{id})와 값 형식으로 넣되, 한 건씩이 아니라 파이프라인으로 보내 빨리 채운다
@Component
public class CacheSeeder {

	private static final String CACHE_NAME = "products";

	private static final int BATCH_SIZE = 10_000;

	private final RedisConnectionFactory connectionFactory;

	private final RedisCacheManager cacheManager;

	public CacheSeeder(RedisConnectionFactory connectionFactory, RedisCacheManager cacheManager) {
		this.connectionFactory = connectionFactory;
		this.cacheManager = cacheManager;
	}

	public void seed(int count) {
		RedisCacheConfiguration config = ((RedisCache) cacheManager.getCache(CACHE_NAME)).getCacheConfiguration();
		String keyPrefix = config.getKeyPrefixFor(CACHE_NAME);
		try (RedisConnection connection = connectionFactory.getConnection()) {
			for (long from = 1; from <= count; from += BATCH_SIZE) {
				connection.openPipeline();
				for (long id = from; id < from + BATCH_SIZE && id <= count; id++) {
					byte[] key = (keyPrefix + id).getBytes(StandardCharsets.UTF_8);
					byte[] value = ByteUtils.getBytes(config.getValueSerializationPair().write(new Product(id, "상품" + id)));
					connection.stringCommands().set(key, value);
				}
				connection.closePipeline();
			}
		}
	}

}
