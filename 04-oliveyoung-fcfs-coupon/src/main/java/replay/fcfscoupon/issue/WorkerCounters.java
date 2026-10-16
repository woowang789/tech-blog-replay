package replay.fcfscoupon.issue;

import java.util.concurrent.atomic.AtomicLong;

import org.springframework.stereotype.Component;

// 워커가 처리를 끝낸 메시지 수(발급 + 미발급). "발급 성공 응답 − 처리 완료"가 아직 큐에 있거나 워커 손에 있는 요청 수다.
// 4단계: 다시 전달된 메시지 수, 원문 방식으로 롤백한 수, 유니크 제약이 막아 준 중복 수도 센다
@Component
public class WorkerCounters {

	private final AtomicLong handled = new AtomicLong();

	private final AtomicLong redelivered = new AtomicLong();

	private final AtomicLong rolledBack = new AtomicLong();

	private final AtomicLong duplicatePrevented = new AtomicLong();

	public void handled() {
		handled.incrementAndGet();
	}

	public void redelivered() {
		redelivered.incrementAndGet();
	}

	public void rolledBack() {
		rolledBack.incrementAndGet();
	}

	public void duplicatePrevented() {
		duplicatePrevented.incrementAndGet();
	}

	public long handledCount() {
		return handled.get();
	}

	public long redeliveredCount() {
		return redelivered.get();
	}

	public long rolledBackCount() {
		return rolledBack.get();
	}

	public long duplicatePreventedCount() {
		return duplicatePrevented.get();
	}

	public void reset() {
		handled.set(0);
		redelivered.set(0);
		rolledBack.set(0);
		duplicatePrevented.set(0);
	}

}
