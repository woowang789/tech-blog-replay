package replay.connectiondeadlock.ledger;

import java.time.Duration;
import java.time.Instant;
import java.util.EnumMap;
import java.util.Map;
import java.util.NoSuchElementException;
import java.util.Optional;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import replay.connectiondeadlock.claim.Claim;
import replay.connectiondeadlock.claim.ClaimRepository;

// 권하는 구조의 알림 원장을 다룬다. 트랜잭션은 모두 짧게, 커넥션을 하나만 쓴다
@Service
@ConditionalOnProperty(name = "replay.notice-design", havingValue = "ledger")
public class NotificationService {

	private final NotificationRepository notificationRepository;

	private final ClaimRepository claimRepository;

	// SENDING인 채 이보다 오래되면 다시 선점할 수 있다
	private final Duration claimLease;

	public NotificationService(NotificationRepository notificationRepository, ClaimRepository claimRepository,
			@Value("${replay.claim-lease}") Duration claimLease) {
		this.notificationRepository = notificationRepository;
		this.claimRepository = claimRepository;
		this.claimLease = claimLease;
	}

	// 비즈니스 트랜잭션 자리: 알림 요청을 원장에 남긴다.
	// 반품 완료 같은 비즈니스 변경과 같은 트랜잭션에서 커밋되므로, 변경이 커밋되면 요청도 반드시 남는다(outbox)
	@Transactional
	public void request(long[] claimIds) {
		for (long claimId : claimIds) {
			notificationRepository.save(new Notification(claimId));
		}
	}

	// 선점: 내가 보낼 차례면 보낼 내용을 돌려준다. 이미 보냈거나 다른 소비자가 보내는 중이면 비어 있다
	@Transactional
	public Optional<Outgoing> claim(long notificationId) {
		Instant now = Instant.now();
		if (notificationRepository.claim(notificationId, now, now.minus(claimLease)) == 0) {
			return Optional.empty();
		}
		Notification notification = notificationRepository.findById(notificationId).orElseThrow();
		Claim claim = claimRepository.findById(notification.getClaimId())
			.orElseThrow(() -> new NoSuchElementException("클레임 없음 claimId=" + notification.getClaimId()));
		// NoticeService와 같은 템플릿
		String message = "[올리브영] " + claim.getCustomerName() + "님, 반품이 완료되었습니다.";
		return Optional.of(new Outgoing(notificationId, claim.getId(), message));
	}

	// 기록: 보냈다는 사실과 외부 API가 돌려준 발송 ID를 남긴다
	@Transactional
	public void markSent(long notificationId, String providerMessageId) {
		notificationRepository.markSent(notificationId, providerMessageId, Instant.now());
	}

	public Map<NotificationStatus, Long> countByStatus() {
		Map<NotificationStatus, Long> counts = new EnumMap<>(NotificationStatus.class);
		for (NotificationStatus status : NotificationStatus.values()) {
			counts.put(status, notificationRepository.countByStatus(status));
		}
		return counts;
	}

	// 보낼 알림: 알림 ID(멱등 키), 실패 주입에 쓰는 클레임 ID, 보낼 내용
	public record Outgoing(long id, long claimId, String message) {

	}

}
