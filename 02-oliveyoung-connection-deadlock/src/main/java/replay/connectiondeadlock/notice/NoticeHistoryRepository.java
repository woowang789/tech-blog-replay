package replay.connectiondeadlock.notice;

import org.springframework.data.jpa.repository.JpaRepository;

public interface NoticeHistoryRepository extends JpaRepository<NoticeHistory, Long> {

}
