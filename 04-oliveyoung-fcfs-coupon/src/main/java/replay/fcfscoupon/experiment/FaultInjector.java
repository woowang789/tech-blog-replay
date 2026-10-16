package replay.fcfscoupon.experiment;

import java.util.concurrent.atomic.AtomicLong;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.stereotype.Component;

// 4단계: 성공 응답 뒤에 생길 수 있는 실패를 코드로 일으킨다(스위치 FAULT). 사용자 번호가 FAULT_EVERY의 배수인 요청에만 건다.
// 워커 쪽 실패는 첫 전달에서만 일으켜, 메시지가 다시 오면(재전달) 성공하게 한다. 프로세스가 실제로 죽는 것을 예외로 흉내 낸 것이다
@Component
public class FaultInjector {

	public enum Fault {
		NONE, // 실패 없음
		DB_ERROR, // 워커가 DB에 저장하려는 순간 DB 오류 (원문이 "DB 처리 실패 시 롤백"이라 한 상황)
		CRASH_BEFORE_ACK, // 워커가 DB에 저장한 뒤 ack하기 전에 죽음 → 브로커가 메시지를 다시 보낸다
		FRONT_CRASH // 앞단이 countReq를 올린 뒤 count를 올리기 전에 죽음 → 두 키가 어긋난다
	}

	private final Fault fault;

	private final int every;

	private final AtomicLong injected = new AtomicLong();

	public FaultInjector(@Value("${replay.fault}") String fault, @Value("${replay.fault-every}") int every) {
		this.fault = switch (fault) {
			case "none" -> Fault.NONE;
			case "db-error" -> Fault.DB_ERROR;
			case "crash-before-ack" -> Fault.CRASH_BEFORE_ACK;
			case "front-crash" -> Fault.FRONT_CRASH;
			default -> throw new IllegalArgumentException("모르는 fault: " + fault + " (none, db-error, crash-before-ack, front-crash 중 하나)");
		};
		this.every = every;
	}

	private boolean hits(long userId) {
		return userId % every == 0;
	}

	// 앞단: countReq를 올린 뒤 count를 올리기 전
	public void maybeFrontCrash(long userId) {
		if (fault == Fault.FRONT_CRASH && hits(userId)) {
			injected.incrementAndGet();
			throw new IllegalStateException("주입한 실패: countReq를 올린 뒤 앱이 죽음 (사용자 " + userId + ")");
		}
	}

	// 워커: DB에 저장하려는 순간
	public void maybeDbError(long userId, boolean redelivered) {
		if (fault == Fault.DB_ERROR && !redelivered && hits(userId)) {
			injected.incrementAndGet();
			throw new DataAccessResourceFailureException("주입한 실패: DB 저장 실패 (사용자 " + userId + ")");
		}
	}

	// 워커: DB에 저장한 뒤 ack하기 전
	public void maybeCrashBeforeAck(long userId, boolean redelivered) {
		if (fault == Fault.CRASH_BEFORE_ACK && !redelivered && hits(userId)) {
			injected.incrementAndGet();
			throw new IllegalStateException("주입한 실패: 저장 뒤 ack 전에 워커가 죽음 (사용자 " + userId + ")");
		}
	}

	public Fault fault() {
		return fault;
	}

	public long injectedCount() {
		return injected.get();
	}

	public void reset() {
		injected.set(0);
	}

}
