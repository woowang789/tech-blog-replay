package replay.connectiondeadlock.notice;

// SQS에 싣는 알림 메시지. 원문처럼 알림에 필요한 최소한의 데이터만 담는다
public record NoticeMessage(long claimId) {

}
