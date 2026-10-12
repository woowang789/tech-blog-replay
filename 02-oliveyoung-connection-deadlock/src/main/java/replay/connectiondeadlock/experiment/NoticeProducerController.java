package replay.connectiondeadlock.experiment;

import java.util.Map;

import io.awspring.cloud.sqs.operations.SqsTemplate;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import replay.connectiondeadlock.notice.NoticeMessage;

// 실험용: 알림 메시지를 count건 SQS에 넣는다. 원문에서 각 비즈니스 로직이 알림 발송 API를 호출하는 부분이다
@RestController
@RequestMapping("/experiments")
public class NoticeProducerController {

	private final SqsTemplate sqsTemplate;

	private final String queueName;

	private final Fault fault;

	public NoticeProducerController(SqsTemplate sqsTemplate, @Value("${replay.queue-name}") String queueName,
			Fault fault) {
		this.sqsTemplate = sqsTemplate;
		this.queueName = queueName;
		this.fault = fault;
	}

	@PostMapping("/notices")
	public Map<String, Object> publish(@RequestParam(defaultValue = "10") int count) {
		int failed = 0;
		for (long claimId : ClaimIds.pick(count)) {
			// 4단계 실패 주입: 발행이 실패한다. 이 구조에는 다시 발행할 근거가 남지 않는다
			if (fault.hit("publish", claimId)) {
				failed++;
				continue;
			}
			sqsTemplate.send(queueName, new NoticeMessage(claimId));
		}
		return Map.of("published", count - failed, "failed", failed);
	}

}
