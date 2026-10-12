package replay.connectiondeadlock.notice;

import java.time.Instant;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

// 원문: 이력 저장 로직에 REQUIRES_NEW를 써서, 알림 한 건을 처리하는 데 커넥션이 2개 필요했다
@Service
public class NoticeHistoryService {

	private final NoticeHistoryRepository noticeHistoryRepository;

	public NoticeHistoryService(NoticeHistoryRepository noticeHistoryRepository) {
		this.noticeHistoryRepository = noticeHistoryRepository;
	}

	// 바깥 트랜잭션과 별개의 트랜잭션을 새로 연다. 바깥 트랜잭션의 커넥션을 쥔 채 커넥션을 하나 더 빌린다
	@Transactional(propagation = Propagation.REQUIRES_NEW)
	public void save(long claimId, String message) {
		noticeHistoryRepository.save(new NoticeHistory(claimId, message, Instant.now()));
	}

	// 원문의 해결 ①: 위 메서드에서 REQUIRES_NEW만 뺐다. 바깥 트랜잭션에 참여해서 바깥 트랜잭션의 커넥션을 같이 쓴다
	@Transactional
	public void saveInOuterTransaction(long claimId, String message) {
		noticeHistoryRepository.save(new NoticeHistory(claimId, message, Instant.now()));
	}

}
