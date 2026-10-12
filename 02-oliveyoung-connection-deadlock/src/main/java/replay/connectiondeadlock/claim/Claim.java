package replay.connectiondeadlock.claim;

import jakarta.persistence.Entity;
import jakarta.persistence.Id;

// 알림톡에 들어갈 클레임(반품, 교환 등) 정보. 알림 발송 전에 조회한다
@Entity
public class Claim {

	@Id
	private Long id;

	private String customerName;

	protected Claim() {
	}

	public Long getId() {
		return id;
	}

	public String getCustomerName() {
		return customerName;
	}

}
