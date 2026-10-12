package replay.connectiondeadlock.experiment;

import java.util.Map;
import java.util.concurrent.ThreadLocalRandom;

import io.awspring.cloud.sqs.operations.SqsTemplate;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import replay.connectiondeadlock.claim.ClaimDataInitializer;
import replay.connectiondeadlock.notice.NoticeMessage;

// 실험용: 알림 메시지를 count건 SQS에 넣는다. 원문에서 각 비즈니스 로직이 알림 발송 API를 호출하는 부분이다
@RestController
@RequestMapping("/experiments")
public class NoticeProducerController {

	private final SqsTemplate sqsTemplate;

	private final String queueName;

	public NoticeProducerController(SqsTemplate sqsTemplate, @Value("${replay.queue-name}") String queueName) {
		this.sqsTemplate = sqsTemplate;
		this.queueName = queueName;
	}

	@PostMapping("/notices")
	public Map<String, Object> publish(@RequestParam(defaultValue = "10") int count) {
		for (int i = 0; i < count; i++) {
			long claimId = ThreadLocalRandom.current().nextLong(1, ClaimDataInitializer.CLAIM_COUNT + 1);
			sqsTemplate.send(queueName, new NoticeMessage(claimId));
		}
		return Map.of("published", count);
	}

}
