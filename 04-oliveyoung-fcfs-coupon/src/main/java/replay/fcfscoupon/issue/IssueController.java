package replay.fcfscoupon.issue;

import java.util.Map;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

// 선착순 쿠폰 발급 요청 API. 사용자가 "쿠폰 받기"를 누르는 지점이다
@RestController
public class IssueController {

	private final IssueService service;

	public IssueController(IssueService service) {
		this.service = service;
	}

	// 200 SUCCESS: 발급 성공 응답(실제 발급은 워커가 한다), 409 SOLD_OUT: 마감
	@PostMapping("/coupons/{couponId}/issue")
	public ResponseEntity<Map<String, String>> issue(@PathVariable String couponId, @RequestParam long userId) {
		IssueResult result = service.request(couponId, userId);
		HttpStatus status = result == IssueResult.SUCCESS ? HttpStatus.OK : HttpStatus.CONFLICT;
		return ResponseEntity.status(status).body(Map.of("result", result.name()));
	}

}
