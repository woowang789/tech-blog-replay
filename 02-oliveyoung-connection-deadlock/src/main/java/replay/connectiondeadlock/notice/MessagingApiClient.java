package replay.connectiondeadlock.notice;

import java.time.Duration;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

// 원문의 Messaging API(사내 알림톡 발송 API) 대신, 응답하는 데 걸리는 시간만큼 기다린다.
// 4단계: 고객이 실제로 받은 알림톡을 센다. 멱등 키를 지원하면 같은 키로 다시 와도 한 번만 보낸다
@Component
public class MessagingApiClient {

	private final Duration latency;

	private final boolean idempotencySupported;

	// API를 부른 횟수. 처리를 끝낸 알림 수(notice.completed)와 비교한다
	private final Counter calls;

	// 고객에게 실제로 나간 알림톡 수. 같은 알림이 두 번 나가면 두 번 센다
	private final Counter delivered;

	// 고객이 받은 알림톡 내용별 받은 횟수. 크기가 고객이 받은 서로 다른 알림 수다
	private final Map<String, Integer> received = new ConcurrentHashMap<>();

	// 받은 멱등 키와 그때 돌려준 발송 ID
	private final Map<String, String> sentKeys = new ConcurrentHashMap<>();

	public MessagingApiClient(@Value("${replay.messaging-api-latency}") Duration latency,
			@Value("${replay.provider-idempotency}") boolean idempotencySupported, MeterRegistry meterRegistry) {
		this.latency = latency;
		this.idempotencySupported = idempotencySupported;
		this.calls = Counter.builder("notice.api.calls").register(meterRegistry);
		this.delivered = Counter.builder("notice.delivered").register(meterRegistry);
	}

	// 멱등 키 없이 보낸다. 부를 때마다 나간다 (1~3단계, 4단계의 올리브영 구조)
	public String send(String message) {
		return send(message, null);
	}

	// 4단계 권하는 구조: 알림 ID를 멱등 키로 같이 보낸다
	public String send(String message, String idempotencyKey) {
		try {
			Thread.sleep(latency);
		}
		catch (InterruptedException ex) {
			Thread.currentThread().interrupt();
			throw new IllegalStateException("Messaging API 호출 중 인터럽트", ex);
		}
		calls.increment();
		String messageId = UUID.randomUUID().toString();
		if (idempotencyKey != null && idempotencySupported) {
			String earlier = sentKeys.putIfAbsent(idempotencyKey, messageId);
			if (earlier != null) {
				// 이미 보낸 키: 다시 보내지 않고 처음 발송 ID를 돌려준다
				return earlier;
			}
		}
		received.merge(message, 1, Integer::sum);
		delivered.increment();
		return messageId;
	}

	public long calls() {
		return (long) calls.count();
	}

	public long delivered() {
		return (long) delivered.count();
	}

	public int customers() {
		return received.size();
	}

}
