package replay.connectiondeadlock.ledger;

import java.time.Instant;
import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.transaction.annotation.Transactional;

public interface NotificationRepository extends JpaRepository<Notification, Long> {

	// 릴레이: 아직 발행하지 않은 요청
	List<Notification> findTop100ByPublishedAtIsNullOrderByIdAsc();

	@Transactional
	@Modifying
	@Query("update Notification n set n.publishedAt = :now where n.id = :id")
	void markPublished(long id, Instant now);

	// 선점: 요청 상태이거나, SENDING인 채 선점 유효 시간이 지났으면 내가 보낸다.
	// 바뀐 행이 없으면 이미 보냈거나 다른 소비자가 보내는 중이다
	@Modifying
	@Query(value = """
			update notification set status = 'SENDING', claimed_at = :now, attempts = attempts + 1
			where id = :id and (status = 'REQUESTED' or (status = 'SENDING' and claimed_at < :staleBefore))
			""", nativeQuery = true)
	int claim(long id, Instant now, Instant staleBefore);

	@Modifying
	@Query(value = "update notification set status = 'SENT', provider_message_id = :providerMessageId, sent_at = :now where id = :id",
			nativeQuery = true)
	void markSent(long id, String providerMessageId, Instant now);

	long countByStatus(NotificationStatus status);

}
