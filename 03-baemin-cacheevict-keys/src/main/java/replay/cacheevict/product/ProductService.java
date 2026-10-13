package replay.cacheevict.product;

import java.time.Duration;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.cache.annotation.CacheEvict;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;

@Service
public class ProductService {

	private final Duration loadLatency;

	public ProductService(@Value("${replay.product-load-latency}") Duration loadLatency) {
		this.loadLatency = loadLatency;
	}

	// 캐시에 없으면 가짜 DB에서 읽어 와 products::{id}에 담는다
	@Cacheable("products")
	public Product getProduct(long id) {
		try {
			Thread.sleep(loadLatency);
		}
		catch (InterruptedException ex) {
			Thread.currentThread().interrupt();
			throw new IllegalStateException("상품 조회 중 인터럽트", ex);
		}
		return new Product(id, "상품" + id);
	}

	// 원문의 문제: allEntries = true면 products 캐시를 통째로 지운다.
	// Spring Data Redis 기본값으로는 KEYS products::* 로 키를 모두 찾고, 찾은 키를 DEL 한 번으로 지운다
	@CacheEvict(cacheNames = "products", allEntries = true)
	public void evictAll() {
	}

}
