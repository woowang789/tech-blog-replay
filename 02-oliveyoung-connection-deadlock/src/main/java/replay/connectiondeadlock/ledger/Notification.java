package replay.connectiondeadlock.ledger;

import java.time.Instant;

import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;

// 권하는 구조의 알림 원장. 비즈니스 트랜잭션에서 알림 요청을 남기고(outbox), 발송 상태까지 여기에 기록한다.
// id가 곧 멱등 키다
@Entity
public class Notification {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	private Long claimId;

	@Enumerated(EnumType.STRING)
	private NotificationStatus status;

	// 릴레이가 SQS에 발행한 시각. 비어 있으면 아직 발행하지 않은 요청이다
	private Instant publishedAt;

	// 소비자가 발송을 선점한 시각과 선점한 횟수
	private Instant claimedAt;

	private int attempts;

	// 외부 API가 돌려준 발송 ID와 기록한 시각
	private String providerMessageId;

	private Instant sentAt;

	protected Notification() {
	}

	public Notification(Long claimId) {
		this.claimId = claimId;
		this.status = NotificationStatus.REQUESTED;
	}

	public Long getId() {
		return id;
	}

	public Long getClaimId() {
		return claimId;
	}

}
