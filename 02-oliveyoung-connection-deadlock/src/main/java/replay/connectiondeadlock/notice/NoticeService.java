package replay.connectiondeadlock.notice;

import java.util.NoSuchElementException;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import replay.connectiondeadlock.claim.Claim;
import replay.connectiondeadlock.claim.ClaimRepository;

// 원문의 NoticeSender.send(): 검증 및 데이터 조회 → 템플릿 생성 → Messaging API 호출 → 알림 내역 저장
@Service
public class NoticeService {

	private static final Logger log = LoggerFactory.getLogger(NoticeService.class);

	private final ClaimRepository claimRepository;

	private final MessagingApiClient messagingApiClient;

	private final NoticeHistoryService noticeHistoryService;

	// 알림 내역까지 저장해 처리를 끝낸 알림 수
	private final Counter completed;

	// 3단계 스위치: false면 원문의 해결 ①대로 REQUIRES_NEW 없이 이력을 저장한다
	private final boolean historyRequiresNew;

	public NoticeService(ClaimRepository claimRepository, MessagingApiClient messagingApiClient,
			NoticeHistoryService noticeHistoryService, MeterRegistry meterRegistry,
			@Value("${replay.history-requires-new}") boolean historyRequiresNew) {
		this.claimRepository = claimRepository;
		this.messagingApiClient = messagingApiClient;
		this.noticeHistoryService = noticeHistoryService;
		this.completed = Counter.builder("notice.completed").register(meterRegistry);
		this.historyRequiresNew = historyRequiresNew;
	}

	// 트랜잭션이 시작될 때 DB 커넥션을 하나 빌리고, 메서드가 끝나야 반납한다
	@Transactional
	public void send(long claimId) {
		Claim claim = claimRepository.findById(claimId)
			.orElseThrow(() -> new NoSuchElementException("클레임 없음 claimId=" + claimId));
		String message = "[올리브영] " + claim.getCustomerName() + "님, 반품이 완료되었습니다.";
		// 커넥션을 쥔 채 외부 API 응답을 기다린다
		messagingApiClient.send(message);
		if (historyRequiresNew) {
			// REQUIRES_NEW라서 커넥션을 하나 더 빌려야 한다
			noticeHistoryService.save(claimId, message);
		}
		else {
			// 원문의 해결 ①: 바깥 트랜잭션의 커넥션을 같이 쓴다
			noticeHistoryService.saveInOuterTransaction(claimId, message);
		}
		completed.increment();
		log.info("알림 발송 완료 claimId={}", claimId);
	}

}
