package replay.connectiondeadlock.notice;

import io.awspring.cloud.sqs.annotation.SqsListener;

import org.springframework.stereotype.Component;

// 원문의 Listener. Spring Cloud AWS가 큐에서 가져온 메시지를 메시지마다 별도 스레드에서 이 메서드로 넘긴다.
// 예외가 나면 메시지를 지우지 않아서, 가시성 타임아웃이 지나면 같은 메시지가 다시 들어온다
@Component
public class NoticeListener {

	private final NoticeService noticeService;

	public NoticeListener(NoticeService noticeService) {
		this.noticeService = noticeService;
	}

	@SqsListener("${replay.queue-name}")
	public void consume(NoticeMessage message) {
		noticeService.send(message.claimId());
	}

}
