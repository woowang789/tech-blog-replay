package replay.fcfscoupon.issue;

import java.util.concurrent.atomic.AtomicLong;

import org.springframework.stereotype.Component;

// 워커가 처리를 끝낸 메시지 수(발급 + 미발급). "발급 성공 응답 − 처리 완료"가 아직 큐에 있거나 워커 손에 있는 요청 수다
@Component
public class WorkerCounters {

	private final AtomicLong handled = new AtomicLong();

	public void handled() {
		handled.incrementAndGet();
	}

	public long handledCount() {
		return handled.get();
	}

	public void reset() {
		handled.set(0);
	}

}
