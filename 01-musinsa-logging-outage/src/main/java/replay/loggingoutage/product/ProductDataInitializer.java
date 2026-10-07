package replay.loggingoutage.product;

import java.util.List;
import java.util.stream.IntStream;

import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

@Component
class ProductDataInitializer implements ApplicationRunner {

	static final int PRODUCT_COUNT = 1_000;

	private final JdbcTemplate jdbcTemplate;

	ProductDataInitializer(JdbcTemplate jdbcTemplate) {
		this.jdbcTemplate = jdbcTemplate;
	}

	// ddl-auto=create라서 기동할 때마다 빈 테이블에 다시 채운다
	@Override
	public void run(ApplicationArguments args) {
		List<Object[]> rows = IntStream.rangeClosed(1, PRODUCT_COUNT)
			.mapToObj(id -> new Object[] { id, "상품-" + id, id * 1_000L })
			.toList();
		jdbcTemplate.batchUpdate("insert into product (id, name, price) values (?, ?, ?)", rows);
	}

}
