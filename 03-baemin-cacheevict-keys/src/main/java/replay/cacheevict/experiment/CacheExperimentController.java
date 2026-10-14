package replay.cacheevict.experiment;

import java.util.Map;

import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import replay.cacheevict.product.ProductService;

// 실험용: 캐시를 채우고(seed, 기본은 products 캐시), 원문의 @CacheEvict(allEntries = true)를 부른다(evict-all)
@RestController
@RequestMapping("/experiments")
public class CacheExperimentController {

	private final CacheSeeder cacheSeeder;

	private final ProductService productService;

	public CacheExperimentController(CacheSeeder cacheSeeder, ProductService productService) {
		this.cacheSeeder = cacheSeeder;
		this.productService = productService;
	}

	@PostMapping("/seed")
	public Map<String, Object> seed(@RequestParam(defaultValue = "1000000") int count,
			@RequestParam(defaultValue = "products") String cache) {
		long started = System.nanoTime();
		cacheSeeder.seed(cache, count);
		return Map.of("cache", cache, "seeded", count, "elapsedMs", (System.nanoTime() - started) / 1_000_000);
	}

	@PostMapping("/evict-all")
	public Map<String, Object> evictAll() {
		long started = System.nanoTime();
		productService.evictAll();
		return Map.of("elapsedMs", (System.nanoTime() - started) / 1_000_000);
	}

}
