package replay.connectiondeadlock;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

// 스케줄링은 4단계 권하는 구조의 outbox 릴레이(NotificationRelay)가 쓴다
@EnableScheduling
@SpringBootApplication
public class ConnectionDeadlockApplication {

	public static void main(String[] args) {
		SpringApplication.run(ConnectionDeadlockApplication.class, args);
	}

}
