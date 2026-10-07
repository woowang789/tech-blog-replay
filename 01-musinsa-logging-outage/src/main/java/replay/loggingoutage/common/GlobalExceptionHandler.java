package replay.loggingoutage.common;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.transaction.CannotCreateTransactionException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public class GlobalExceptionHandler {

	private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

	// connection-timeout(30초) 안에 커넥션을 빌리지 못하면 트랜잭션 시작 단계에서 실패한다.
	// 실패마다 스택 트레이스를 찍으면 그 로그도 같은 파이프를 채우므로 한 줄만 남긴다.
	@ExceptionHandler(CannotCreateTransactionException.class)
	public ResponseEntity<String> handleConnectionUnavailable(CannotCreateTransactionException e) {
		log.warn("DB 커넥션 획득 실패: {}", e.getMostSpecificCause().getMessage());
		return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE).body("DB connection unavailable");
	}

}
