package replay.fcfscoupon.coupon;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

// 4단계 스위치 IDEMPOTENT: true면 앱이 뜰 때 발급 내역에 (coupon_id, user_id) 유니크 제약을 건다.
// 같은 사용자에게 두 번 저장하려는 시도(다시 전달된 메시지)를 DB가 막는다. 테이블은 앱이 뜰 때마다 새로 만들어져(ddl-auto: create) 제약도 매번 건다
@Component
class IssueUniqueness implements ApplicationRunner {

	private final JdbcTemplate jdbc;

	private final boolean idempotent;

	IssueUniqueness(JdbcTemplate jdbc, @Value("${replay.idempotent}") boolean idempotent) {
		this.jdbc = jdbc;
		this.idempotent = idempotent;
	}

	@Override
	public void run(ApplicationArguments args) {
		if (idempotent) {
			jdbc.execute("ALTER TABLE coupon_issues ADD CONSTRAINT uk_coupon_user UNIQUE (coupon_id, user_id)");
		}
	}

}
