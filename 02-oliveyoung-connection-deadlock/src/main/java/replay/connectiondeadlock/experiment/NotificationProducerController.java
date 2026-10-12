package replay.connectiondeadlock.experiment;

import java.util.Map;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import replay.connectiondeadlock.ledger.NotificationService;

// 실험용(4단계 권하는 구조): 알림 요청 count건을 원장에 남긴다.
// 원문에서 비즈니스 로직이 알림 발송을 요청하는 자리다. SQS에는 직접 넣지 않고 릴레이가 발행한다
@RestController
@RequestMapping("/experiments")
@ConditionalOnProperty(name = "replay.notice-design", havingValue = "ledger")
public class NotificationProducerController {

	private final NotificationService notificationService;

	public NotificationProducerController(NotificationService notificationService) {
		this.notificationService = notificationService;
	}

	@PostMapping("/notifications")
	public Map<String, Object> request(@RequestParam(defaultValue = "10") int count) {
		notificationService.request(ClaimIds.pick(count));
		return Map.of("requested", count);
	}

}
