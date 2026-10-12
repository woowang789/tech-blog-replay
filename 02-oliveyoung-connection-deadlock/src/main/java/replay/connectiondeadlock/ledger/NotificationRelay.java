package replay.connectiondeadlock.ledger;

import java.time.Instant;

import io.awspring.cloud.sqs.operations.SqsTemplate;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import replay.connectiondeadlock.experiment.Fault;

// 권하는 구조의 outbox 릴레이. 원장에 커밋된 요청 중 아직 발행하지 않은 것을 SQS에 발행하고, 발행 시각을 남긴다.
// 발행한 뒤 시각을 남기기 전에 죽으면 같은 요청을 한 번 더 발행할 수 있다. 그런 중복은 소비자가 원장으로 걸러 낸다
@Component
@ConditionalOnProperty(name = "replay.notice-design", havingValue = "ledger")
public class NotificationRelay {

	private final NotificationRepository notificationRepository;

	private final SqsTemplate sqsTemplate;

	private final String queueName;

	private final Fault fault;

	public NotificationRelay(NotificationRepository notificationRepository, SqsTemplate sqsTemplate,
			@Value("${replay.notification-queue-name}") String queueName, Fault fault) {
		this.notificationRepository = notificationRepository;
		this.sqsTemplate = sqsTemplate;
		this.queueName = queueName;
		this.fault = fault;
	}

	@Scheduled(fixedDelayString = "${replay.relay-interval}")
	public void publish() {
		for (Notification notification : notificationRepository.findTop100ByPublishedAtIsNullOrderByIdAsc()) {
			// 4단계 실패 주입: 발행이 실패한다. 시각을 남기지 않아서 다음 차례에 다시 발행한다
			if (fault.hit("publish", notification.getClaimId())) {
				continue;
			}
			sqsTemplate.send(queueName, new NotificationMessage(notification.getId()));
			notificationRepository.markPublished(notification.getId(), Instant.now());
		}
	}

}
