"""evidence.sh가 모은 층별 증거(스레드 덤프, HikariCP, MySQL, SQS)를 서로 맞춰 본다.

사용법: python3 scripts/evidence_report.py results/evidence-시각
"""
import sys
from pathlib import Path

from thread_dump_summary import is_listener, split_threads


def main(directory):
    d = Path(directory)

    threads = [t for t in split_threads((d / "threads.txt").read_text(encoding="utf-8")) if is_listener(t)]
    # NoticeService.send 본문 안이면 바깥 트랜잭션이 이미 커넥션을 1개 쥐고 있다
    holding = [t for t in threads if "NoticeService.send(" in t]
    waiting_second = [t for t in holding if "HikariPool.getConnection" in t]
    waiting_first = [t for t in threads if "HikariPool.getConnection" in t and t not in holding]

    hikari = dict(line.split() for line in (d / "hikari.txt").read_text().splitlines())

    rows = [line.split("\t") for line in (d / "mysql.tsv").read_text(encoding="utf-8").splitlines() if line]
    commands = {}
    for row in rows:
        commands[row[1]] = commands.get(row[1], 0) + 1
    open_trx = [int(row[3]) for row in rows if row[3]]
    running = [row for row in rows if row[1] == "Query"]

    print("== ① 덤프: SQS 리스너 스레드")
    print(f"  커넥션을 쥔 스레드 (NoticeService.send 본문 안)      : {len(holding)}개")
    print(f"    그중 커넥션을 하나 더 기다리는 스레드 (REQUIRES_NEW) : {len(waiting_second)}개")
    print(f"  첫 커넥션을 기다리는 스레드 (바깥 트랜잭션 시작)      : {len(waiting_first)}개")
    print("== ② HikariCP")
    print(f"  active {hikari['active']}, idle {hikari['idle']}, pending {hikari['pending']} "
          f"(전체 {hikari['total']}), 누적 타임아웃 {hikari['timeout']}")
    print(f"== ③ MySQL: 앱 커넥션 {len(rows)}개")
    print(f"  상태별: {', '.join(f'{k} {v}개' for k, v in sorted(commands.items()))}")
    oldest = f", 가장 오래된 것 {max(open_trx)}초째" if open_trx else ""
    print(f"  열린 트랜잭션 {len(open_trx)}개{oldest}")
    print(f"  실행 중인 쿼리 {len(running)}개")
    print("== ④ 맞춰 보기")
    print(f"  커넥션을 쥔 스레드 {len(holding)} / HikariCP active {hikari['active']} / MySQL 열린 트랜잭션 {len(open_trx)}")
    print(f"  커넥션을 기다리는 스레드 {len(waiting_second) + len(waiting_first)} / HikariCP pending {hikari['pending']}")
    print("== ⑤ SQS")
    print("  " + (d / "queue.txt").read_text(encoding="utf-8").strip().replace("\n", "\n  "))


if __name__ == "__main__":
    main(sys.argv[1])
