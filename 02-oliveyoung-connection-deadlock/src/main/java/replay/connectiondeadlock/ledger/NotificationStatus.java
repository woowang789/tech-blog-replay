package replay.connectiondeadlock.ledger;

// 알림 원장의 상태: 요청됨 → 보내는 중(선점) → 보냄
public enum NotificationStatus {

	REQUESTED, SENDING, SENT

}
