package replay.cacheevict;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.cache.autoconfigure.RedisCacheManagerBuilderCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.cache.BatchStrategies;
import org.springframework.data.redis.cache.RedisCacheWriter;
import org.springframework.data.redis.connection.RedisConnectionFactory;

// 스위치: 캐시 쓰기 도구를 Spring Boot 기본(4.x: Lettuce면 비동기 쓰기, 전체 삭제는 KEYS, 잠금 없음)과 다르게 만든다.
// 하나라도 켜면 RedisCacheWriter.create로 캐시 쓰기 도구를 새로 만들어 바꿔 끼운다. 모두 기본값이면 Boot가 만든 것을 그대로 쓴다.
//   cache-immediate-writes  true면 원문(Spring Data Redis 3.3.7)처럼 캐시 쓰기를 동기로 한다(1단계부터)
//   cache-batch-strategy    scan이면 전체 삭제할 키를 KEYS 대신 SCAN으로 찾는다. 원문의 해결책(3단계)
//   cache-scan-batch-size   SCAN 한 번에 가져올 키 수(COUNT)이자 한 번에 지우는 키 수
//   cache-locking           true면 잠금을 쓰는 캐시 쓰기 도구로 바꾼다. 원문이 SCAN이어도 막힌다고 경고한 경우(3단계)
// 원문(3.3.7)은 RedisCacheWriter.nonLockingRedisCacheWriter(factory, BatchStrategies.scan(n))처럼 팩토리 메서드로 바꿨다.
// 4.x에서 동기 쓰기와 함께 고르려면 create에 넘기는 설정 도구로 조합한다
@Configuration(proxyBeanMethods = false)
class CacheWriterConfig {

	@Bean
	RedisCacheManagerBuilderCustomizer cacheWriterSwitches(RedisConnectionFactory connectionFactory,
			@Value("${replay.cache-immediate-writes}") boolean immediateWrites,
			@Value("${replay.cache-batch-strategy}") String batchStrategy,
			@Value("${replay.cache-scan-batch-size}") int scanBatchSize,
			@Value("${replay.cache-locking}") boolean locking) {
		boolean scan = "scan".equals(batchStrategy);
		return builder -> {
			if (!immediateWrites && !scan && !locking) {
				return;
			}
			builder.cacheWriter(RedisCacheWriter.create(connectionFactory, writer -> {
				writer.immediateWrites(immediateWrites);
				if (scan) {
					writer.batchStrategy(BatchStrategies.scan(scanBatchSize));
				}
				if (locking) {
					writer.enableLocking();
				}
			}));
		};
	}

}
