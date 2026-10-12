package replay.connectiondeadlock.ledger;

// 권하는 구조에서 SQS에 싣는 메시지. 알림 ID만 담고, 보낼 내용은 원장과 클레임에서 읽는다
public record NotificationMessage(long notificationId) {

}
