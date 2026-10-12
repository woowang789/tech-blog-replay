"""앱 로그에서 메시지마다 몇 번 처리를 시도했고 끝냈는지 센다.
처리 시도를 시각 순으로 묶어서(2초 넘게 새 시도가 없으면 다음 묶음), 묶음마다 몇 건이 끝났는지도 보여 준다.

사용법: docker compose logs app --no-log-prefix | python3 scripts/attempts.py
"""
import re
import sys
from collections import Counter
from datetime import datetime

START = re.compile(r"메시지 처리 시작 messageId=(\S+) receiveCount=(\d+)")
DONE = re.compile(r"메시지 처리 완료 messageId=(\S+)")
BATCH_GAP_SECONDS = 2


def timestamp(line):
    # 로그는 UTC로 찍혀서 watch.sh와 맞추려고 내 컴퓨터의 시간대로 바꾼다
    return datetime.strptime(line.split(" ", 1)[0], "%Y-%m-%dT%H:%M:%S.%f%z").astimezone()


def main(lines):
    starts, done = [], {}
    for line in lines:
        if m := START.search(line):
            starts.append((timestamp(line), m.group(1), int(m.group(2))))
        elif m := DONE.search(line):
            done[m.group(1)] = timestamp(line)
    if not starts:
        print("처리 시작 로그가 없다")
        return

    attempts = Counter(message_id for _, message_id, _ in starts)
    print(f"메시지 {len(attempts)}건, 처리 시도 {len(starts)}번, 처리를 끝낸 메시지 {len(done)}건")
    print("시도 횟수별 메시지 수: " + ", ".join(f"{n}번 {c}건" for n, c in sorted(Counter(attempts.values()).items())))
    print(f"가장 큰 receiveCount: {max(count for _, _, count in starts)}")

    # 시도마다 끝냈는지: 그 메시지의 완료 로그가 이 시도 뒤, 같은 메시지의 다음 시도 전에 있으면 이 시도가 끝낸 것이다
    next_start = {}
    for i, (t, message_id, _) in enumerate(starts):
        later = [t2 for t2, m2, _ in starts[i + 1:] if m2 == message_id]
        next_start[i] = later[0] if later else None

    def finished(i):
        t, message_id, _ = starts[i]
        end = done.get(message_id)
        return end is not None and end >= t and (next_start[i] is None or end < next_start[i])

    print(f"\n{'묶음 시작':>12} {'시도':>4} {'첫~끝 시도 간격':>14} {'그중 끝낸 수':>10}")
    batch = [0]
    for i in list(range(1, len(starts))) + [None]:
        if i is not None and (starts[i][0] - starts[batch[-1]][0]).total_seconds() <= BATCH_GAP_SECONDS:
            batch.append(i)
            continue
        spread = (starts[batch[-1]][0] - starts[batch[0]][0]).total_seconds() * 1000
        finished_count = sum(1 for j in batch if finished(j))
        print(f"{starts[batch[0]][0]:%H:%M:%S.%f}"[:12] + f" {len(batch):>5} {spread:>12.0f}ms {finished_count:>12}")
        batch = [i] if i is not None else []


if __name__ == "__main__":
    main(open(sys.argv[1], encoding="utf-8") if len(sys.argv) > 1 else sys.stdin)
