package replay.fcfscoupon.issue;

import java.time.Duration;
import java.util.LongSummaryStatistics;

import org.springframework.stereotype.Component;

// Time Gap 통계: 1차 검증을 통과한 시각부터 워커가 메시지를 받은 시각까지(µs 단위로 모아 ms로 보여 준다)
@Component
public class GapStatistics {

	private LongSummaryStatistics micros = new LongSummaryStatistics();

	public synchronized void record(Duration gap) {
		micros.accept(gap.toNanos() / 1_000);
	}

	public synchronized Snapshot snapshot() {
		if (micros.getCount() == 0) {
			return new Snapshot(0, 0, 0, 0);
		}
		return new Snapshot(micros.getCount(), micros.getMin() / 1000.0, micros.getAverage() / 1000.0,
				micros.getMax() / 1000.0);
	}

	public synchronized void reset() {
		micros = new LongSummaryStatistics();
	}

	public record Snapshot(long count, double minMs, double avgMs, double maxMs) {
	}

}
