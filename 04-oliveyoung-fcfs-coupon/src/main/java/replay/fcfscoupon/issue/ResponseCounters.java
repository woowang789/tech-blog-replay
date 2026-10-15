package replay.fcfscoupon.issue;

import java.util.concurrent.atomic.AtomicLong;

import org.springframework.stereotype.Component;

// 온라인몰이 돌려준 응답 수. "발급 성공" 응답 수와 실제 발급 수(DB)의 차이가 미발급이다
@Component
public class ResponseCounters {

	private final AtomicLong success = new AtomicLong();

	private final AtomicLong soldOut = new AtomicLong();

	public void count(IssueResult result) {
		(result == IssueResult.SUCCESS ? success : soldOut).incrementAndGet();
	}

	public long success() {
		return success.get();
	}

	public long soldOut() {
		return soldOut.get();
	}

	public void reset() {
		success.set(0);
		soldOut.set(0);
	}

}
