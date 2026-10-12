package replay.connectiondeadlock.experiment;

import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

// 4단계 실패 주입: 정한 지점에서 알림 세 건 중 한 건을, 그 알림의 첫 시도에서만 실패시킨다.
//   publish       발행이 실패한다. 알림 요청은 생겼는데 큐에 넣지 못했다
//   after-send    알림톡을 보낸 직후, 보냈다는 기록을 남기기 전에 실패한다
//   after-record  기록까지 커밋한 뒤, 메시지를 지우기 전에 실패한다. 앱이 죽거나 삭제가 실패한 것과 같다
@Component
public class Fault {

	private final String point;

	// 한 번 본 알림. 다시 들어온 알림은 실패시키지 않는다
	private final Set<Long> seen = ConcurrentHashMap.newKeySet();

	private final AtomicLong sequence = new AtomicLong();

	private final Counter injected;

	public Fault(@Value("${replay.fault}") String point, MeterRegistry meterRegistry) {
		this.point = point;
		this.injected = Counter.builder("notice.faults").register(meterRegistry);
	}

	// where 지점에서 실패시킬 차례인지. key는 알림을 구분하는 클레임 ID다
	public boolean hit(String where, long key) {
		if (point.equals(where) && seen.add(key) && sequence.incrementAndGet() % 3 == 0) {
			injected.increment();
			return true;
		}
		return false;
	}

	// 실패시킬 차례면 예외를 던진다
	public void check(String where, long key) {
		if (hit(where, key)) {
			throw new IllegalStateException("실패 주입: " + where + " claimId=" + key);
		}
	}

	public long injected() {
		return (long) injected.count();
	}

}
