package replay.cacheevict;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.cache.autoconfigure.RedisCacheManagerBuilderCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.cache.RedisCacheWriter;
import org.springframework.data.redis.cache.RedisCacheWriter.RedisCacheWriterConfigurer;
import org.springframework.data.redis.connection.RedisConnectionFactory;

// 스위치: 원문(Spring Data Redis 3.3.7)처럼 캐시 쓰기를 동기로 한다.
// 4.x는 Lettuce를 쓰면 비동기 쓰기가 기본이라, @CacheEvict(allEntries = true)의 clear가
// 반응형 연결로 KEYS 뒤 UNLINK를 보내 놓고 기다리지 않는다. immediateWrites를 켜면 원문처럼 KEYS 뒤 DEL을 끝까지 기다린다
@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(name = "replay.cache-immediate-writes", havingValue = "true")
class CacheWriterConfig {

	@Bean
	RedisCacheManagerBuilderCustomizer immediateWrites(RedisConnectionFactory connectionFactory) {
		return builder -> builder
			.cacheWriter(RedisCacheWriter.create(connectionFactory, RedisCacheWriterConfigurer::immediateWrites));
	}

}
