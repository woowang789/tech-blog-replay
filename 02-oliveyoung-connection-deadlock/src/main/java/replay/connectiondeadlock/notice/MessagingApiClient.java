package replay.connectiondeadlock.notice;

import java.time.Duration;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

// 원문의 Messaging API(사내 알림톡 발송 API) 대신, 응답하는 데 걸리는 시간만큼 기다린다
@Component
public class MessagingApiClient {

	private final Duration latency;

	// 알림톡을 실제로 보낸 횟수. 처리를 끝낸 알림 수(notice.completed)와 비교한다
	private final Counter calls;

	public MessagingApiClient(@Value("${replay.messaging-api-latency}") Duration latency, MeterRegistry meterRegistry) {
		this.latency = latency;
		this.calls = Counter.builder("notice.api.calls").register(meterRegistry);
	}

	public void send(String message) {
		try {
			Thread.sleep(latency);
			calls.increment();
		}
		catch (InterruptedException ex) {
			Thread.currentThread().interrupt();
			throw new IllegalStateException("Messaging API 호출 중 인터럽트", ex);
		}
	}

}
