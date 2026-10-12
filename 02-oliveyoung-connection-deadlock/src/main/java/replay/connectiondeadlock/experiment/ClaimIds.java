package replay.connectiondeadlock.experiment;

import java.util.concurrent.ThreadLocalRandom;

import replay.connectiondeadlock.claim.ClaimDataInitializer;

// 실험용: 겹치지 않는 클레임 ID를 count개 고른다.
// 4단계에서 고객이 받은 알림톡을 내용(고객 이름)으로 구분하려고 겹치지 않게 한다
final class ClaimIds {

	private ClaimIds() {
	}

	static long[] pick(int count) {
		return ThreadLocalRandom.current()
			.longs(1, ClaimDataInitializer.CLAIM_COUNT + 1)
			.distinct()
			.limit(count)
			.toArray();
	}

}
