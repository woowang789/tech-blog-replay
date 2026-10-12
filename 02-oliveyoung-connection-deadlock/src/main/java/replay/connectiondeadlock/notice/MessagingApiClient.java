package replay.connectiondeadlock.notice;

import java.time.Duration;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

// 원문의 Messaging API(사내 알림톡 발송 API) 대신, 응답하는 데 걸리는 시간만큼 기다린다
@Component
public class MessagingApiClient {

	private final Duration latency;

	public MessagingApiClient(@Value("${replay.messaging-api-latency}") Duration latency) {
		this.latency = latency;
	}

	public void send(String message) {
		try {
			Thread.sleep(latency);
		}
		catch (InterruptedException ex) {
			Thread.currentThread().interrupt();
			throw new IllegalStateException("Messaging API 호출 중 인터럽트", ex);
		}
	}

}
