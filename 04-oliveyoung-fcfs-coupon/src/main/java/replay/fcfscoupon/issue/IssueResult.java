package replay.fcfscoupon.issue;

// 발급 요청에 대한 온라인몰의 응답. SUCCESS는 1차 검증을 통과해 MQ에 실었다는 뜻이고, 실제 발급은 워커가 나중에 한다
public enum IssueResult {
	SUCCESS, SOLD_OUT
}
