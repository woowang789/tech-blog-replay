package replay.connectiondeadlock.notice;

import io.awspring.cloud.sqs.annotation.SqsListener;
import io.awspring.cloud.sqs.listener.SqsHeaders;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import org.springframework.messaging.handler.annotation.Header;
import org.springframework.stereotype.Component;

import replay.connectiondeadlock.experiment.Fault;

// 원문의 Listener. Spring Cloud AWS가 큐에서 가져온 메시지를 메시지마다 별도 스레드에서 이 메서드로 넘긴다.
// 예외가 나면 메시지를 지우지 않아서, 가시성 타임아웃이 지나면 같은 메시지가 다시 들어온다
@Component
public class NoticeListener {

	private static final Logger log = LoggerFactory.getLogger(NoticeListener.class);

	private final NoticeService noticeService;

	private final Fault fault;

	public NoticeListener(NoticeService noticeService, Fault fault) {
		this.noticeService = noticeService;
		this.fault = fault;
	}

	// 2단계: 같은 메시지가 몇 번째로 들어왔는지(receiveCount) 남겨서, 다시 처리되는 메시지를 셀 수 있게 한다
	@SqsListener("${replay.queue-name}")
	public void consume(NoticeMessage message, @Header(SqsHeaders.SQS_RAW_MESSAGE_ID_HEADER) String messageId,
			@Header(SqsHeaders.MessageSystemAttributes.SQS_APPROXIMATE_RECEIVE_COUNT) String receiveCount) {
		log.info("메시지 처리 시작 messageId={} receiveCount={} claimId={}", messageId, receiveCount, message.claimId());
		noticeService.send(message.claimId());
		// 4단계 실패 주입: 이력까지 커밋한 뒤 메시지를 지우기 전에 실패한다
		fault.check("after-record", message.claimId());
		log.info("메시지 처리 완료 messageId={}", messageId);
	}

}
