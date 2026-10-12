package replay.connectiondeadlock.ledger;

import java.util.Optional;

import io.awspring.cloud.sqs.annotation.SqsListener;
import io.awspring.cloud.sqs.listener.SqsHeaders;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.messaging.handler.annotation.Header;
import org.springframework.stereotype.Component;

import replay.connectiondeadlock.experiment.Fault;
import replay.connectiondeadlock.ledger.NotificationService.Outgoing;
import replay.connectiondeadlock.notice.MessagingApiClient;

// 권하는 구조의 소비자. 메서드 전체에 트랜잭션을 걸지 않는다.
// 선점과 기록만 짧은 트랜잭션으로 하고, 외부 API는 그 사이에 트랜잭션 밖에서 부른다. 알림 ID를 멱등 키로 같이 보낸다
@Component
@ConditionalOnProperty(name = "replay.notice-design", havingValue = "ledger")
public class NotificationListener {

	private static final Logger log = LoggerFactory.getLogger(NotificationListener.class);

	private final NotificationService notificationService;

	private final MessagingApiClient messagingApiClient;

	private final Fault fault;

	public NotificationListener(NotificationService notificationService, MessagingApiClient messagingApiClient,
			Fault fault) {
		this.notificationService = notificationService;
		this.messagingApiClient = messagingApiClient;
		this.fault = fault;
	}

	@SqsListener("${replay.notification-queue-name}")
	public void consume(NotificationMessage message,
			@Header(SqsHeaders.MessageSystemAttributes.SQS_APPROXIMATE_RECEIVE_COUNT) String receiveCount) {
		Optional<Outgoing> claimed = notificationService.claim(message.notificationId());
		if (claimed.isEmpty()) {
			// 이미 보냈거나 다른 소비자가 보내는 중이다. 정상 종료해서 메시지를 지운다
			log.info("알림 건너뜀 notificationId={} receiveCount={}", message.notificationId(), receiveCount);
			return;
		}
		Outgoing outgoing = claimed.get();
		// 트랜잭션 밖: 커넥션을 쥐지 않은 채 외부 API 응답을 기다린다
		String providerMessageId = messagingApiClient.send(outgoing.message(), String.valueOf(outgoing.id()));
		// 4단계 실패 주입: 알림톡은 나갔는데 기록을 남기기 전에 실패한다. 다시 받은 메시지가 같은 멱등 키로 다시 보낸다
		fault.check("after-send", outgoing.claimId());
		notificationService.markSent(outgoing.id(), providerMessageId);
		// 4단계 실패 주입: 기록까지 커밋한 뒤 메시지를 지우기 전에 실패한다. 다시 받은 메시지는 선점에서 걸러진다
		fault.check("after-record", outgoing.claimId());
		log.info("알림 발송 완료 notificationId={} receiveCount={}", outgoing.id(), receiveCount);
	}

}
