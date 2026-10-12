package replay.connectiondeadlock.notice;

import java.time.Instant;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;

// 원문의 "알림 내역 저장" 테이블
@Entity
public class NoticeHistory {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	private Long claimId;

	private String message;

	private Instant sentAt;

	protected NoticeHistory() {
	}

	public NoticeHistory(Long claimId, String message, Instant sentAt) {
		this.claimId = claimId;
		this.message = message;
		this.sentAt = sentAt;
	}

}
