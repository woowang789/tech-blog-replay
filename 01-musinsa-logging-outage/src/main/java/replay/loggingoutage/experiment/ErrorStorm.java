package replay.loggingoutage.experiment;

import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;

import org.springframework.boot.actuate.endpoint.annotation.Endpoint;
import org.springframework.boot.actuate.endpoint.annotation.ReadOperation;
import org.springframework.boot.actuate.endpoint.annotation.WriteOperation;
import org.springframework.stereotype.Component;

// 4-B: 요청마다 ERROR 로그를 스택 트레이스와 함께 남기는 "에러 로그 폭주" 스위치.
// DEBUG 스위치(actuator loggers)처럼 관리 포트(8081)로 켜고 끈다. API 포트(8080)는 장애 중에 응답하지 못해서 거기에 두면 끌 수 없다.
@Component
@Endpoint(id = "errorstorm")
public class ErrorStorm {

	private final AtomicBoolean enabled = new AtomicBoolean();

	public boolean isEnabled() {
		return enabled.get();
	}

	@ReadOperation
	public Map<String, Boolean> state() {
		return Map.of("enabled", enabled.get());
	}

	@WriteOperation
	public Map<String, Boolean> change(boolean enabled) {
		this.enabled.set(enabled);
		return state();
	}

}
