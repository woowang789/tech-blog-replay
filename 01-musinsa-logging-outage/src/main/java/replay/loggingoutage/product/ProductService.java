package replay.loggingoutage.product;

import java.util.NoSuchElementException;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class ProductService {

	private static final Logger log = LoggerFactory.getLogger(ProductService.class);

	private final ProductRepository productRepository;

	private final int debugLinesPerRequest;

	public ProductService(ProductRepository productRepository,
			@Value("${replay.debug-lines-per-request}") int debugLinesPerRequest) {
		this.productRepository = productRepository;
		this.debugLinesPerRequest = debugLinesPerRequest;
	}

	// 트랜잭션이 시작될 때 DB 커넥션을 빌리고, 메서드가 끝나야 반납한다.
	// 그 사이에 찍는 로그는 모두 커넥션을 쥔 채로 stdout에 쓰인다.
	@Transactional(readOnly = true)
	public ProductResponse getProduct(long id) {
		Product product = productRepository.findById(id)
			.orElseThrow(() -> new NoSuchElementException("상품 없음 id=" + id));
		log.info("상품 조회 id={}", id);
		if (log.isDebugEnabled()) {
			// 원문의 "DEBUG를 켜자 쿼리 한 건마다 수십 줄의 로그가 나왔다" 상황
			for (int step = 1; step <= debugLinesPerRequest; step++) {
				log.debug("상품 조회 상세 id={} name={} price={} step={}/{}", id, product.getName(), product.getPrice(),
						step, debugLinesPerRequest);
			}
		}
		return ProductResponse.from(product);
	}

}
