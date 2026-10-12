package replay.connectiondeadlock.claim;

import java.util.List;
import java.util.stream.IntStream;

import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

@Component
public class ClaimDataInitializer implements ApplicationRunner {

	public static final int CLAIM_COUNT = 1_000;

	private final JdbcTemplate jdbcTemplate;

	ClaimDataInitializer(JdbcTemplate jdbcTemplate) {
		this.jdbcTemplate = jdbcTemplate;
	}

	// ddl-auto=create라서 기동할 때마다 빈 테이블에 다시 채운다
	@Override
	public void run(ApplicationArguments args) {
		List<Object[]> rows = IntStream.rangeClosed(1, CLAIM_COUNT)
			.mapToObj(id -> new Object[] { id, "고객" + id })
			.toList();
		jdbcTemplate.batchUpdate("insert into claim (id, customer_name) values (?, ?)", rows);
	}

}
