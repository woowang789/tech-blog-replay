"""jcmd Thread.print -l 결과에서 SQS 리스너 스레드를 '무엇을 기다리는지' 기준으로 나눈다.

사용법: python3 scripts/thread_dump_summary.py results/thread-dump-시각.txt
"""
import sys
import unicodedata

LISTENER = "sqsListenerEndpointContainer"  # Spring Cloud AWS가 메시지를 처리하는 스레드 이름


def pad(text, width):
    # 한글은 터미널에서 두 칸을 차지해서 글자 수가 아니라 화면 폭으로 맞춘다
    shown = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)
    return text + " " * max(0, width - shown)


def split_threads(text):
    blocks, current = [], None
    for line in text.splitlines():
        if line.startswith('"'):
            if current is not None:
                blocks.append("\n".join(current))
            current = [line]
        elif current is not None:
            current.append(line)
    if current is not None:
        blocks.append("\n".join(current))
    return blocks


def classify(block):
    if "HikariPool.getConnection" in block:
        # NoticeService.send 본문 안이면 바깥 트랜잭션이 이미 커넥션을 쥐고 있다
        return "holding" if "NoticeService.send(" in block else "first"
    if "MessagingApiClient.send" in block:
        return "api"
    if "NoticeListener.consume" in block:
        return "working"
    return "idle"


LABELS = {
    "holding": "1) 커넥션 1개를 쥔 채 1개를 더 기다림 (REQUIRES_NEW)",
    "first": "2) 첫 커넥션을 기다림 (바깥 트랜잭션 시작)",
    "api": "3) Messaging API 응답을 기다림",
    "working": "4) 그 밖에 메시지 처리 중",
    "idle": "5) 쉬는 중 (처리할 메시지 없음)",
}


def main(path):
    listeners = [t for t in split_threads(open(path, encoding="utf-8").read()) if LISTENER in t.splitlines()[0]]
    groups = {key: [] for key in LABELS}
    for t in listeners:
        groups[classify(t)].append(t)

    print(f"SQS 리스너 스레드 {len(listeners)}개")
    for key, label in LABELS.items():
        print(f"  {pad(label, 54)}: {len(groups[key]):3d}개")

    example = groups["holding"] or groups["first"]
    if example:
        print("\n[예시] 커넥션을 기다리는 스레드의 스택 (위가 지금 하는 일, 줄 번호 생략)")
        keep = ("HikariPool.getConnection", "JpaTransactionManager.doBegin", "TransactionInterceptor.invoke",
                "NoticeHistoryService", "NoticeService", "NoticeListener.consume")
        lines = example[0].splitlines()
        print(lines[0][:100])
        shown = set()
        for line in lines[1:]:
            frame = line.strip().removeprefix("at ").split("(")[0]
            if any(k in frame for k in keep) and frame not in shown:
                shown.add(frame)
                print(f"   {frame}")


if __name__ == "__main__":
    main(sys.argv[1])
