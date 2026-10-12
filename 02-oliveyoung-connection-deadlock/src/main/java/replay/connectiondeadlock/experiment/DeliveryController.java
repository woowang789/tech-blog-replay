package replay.connectiondeadlock.experiment;

import java.util.LinkedHashMap;
import java.util.Map;

import org.springframework.beans.factory.ObjectProvider;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import replay.connectiondeadlock.ledger.NotificationService;
import replay.connectiondeadlock.notice.MessagingApiClient;

// 실험용(4단계): 고객이 받은 알림톡, 실패 주입 횟수, 원장 상태를 돌려준다. delivery.py가 읽는다
@RestController
@RequestMapping("/experiments")
public class DeliveryController {

	private final MessagingApiClient messagingApiClient;

	private final Fault fault;

	// 원장은 권하는 구조에만 있다
	private final ObjectProvider<NotificationService> notificationService;

	public DeliveryController(MessagingApiClient messagingApiClient, Fault fault,
			ObjectProvider<NotificationService> notificationService) {
		this.messagingApiClient = messagingApiClient;
		this.fault = fault;
		this.notificationService = notificationService;
	}

	@GetMapping("/deliveries")
	public Map<String, Object> deliveries() {
		Map<String, Object> result = new LinkedHashMap<>();
		result.put("apiCalls", messagingApiClient.calls());
		result.put("delivered", messagingApiClient.delivered());
		result.put("customers", messagingApiClient.customers());
		result.put("faults", fault.injected());
		notificationService.ifAvailable(service -> result.put("ledger", service.countByStatus()));
		return result;
	}

}
