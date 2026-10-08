"""evidence.sh가 모은 층별 증거(커널, JVM, HikariCP, MySQL)를 서로 맞춰 본다.

사용법: python3 scripts/evidence_report.py results/evidence-시각
"""
import sys
from collections import Counter
from pathlib import Path

from thread_dump_summary import (classify, is_holding_connection, is_logging_failure, jvm_state, lock_owner,
                                 native_tid, split_threads, thread_name)

# 아키텍처별 write 시스템 콜 번호
WRITE_SYSCALL = {"aarch64": "64", "x86_64": "1"}


def read_tsv(path, columns):
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        values = line.split("\t")
        rows.append(dict(zip(columns, values + [""] * (len(columns) - len(values)))))
    return rows


def main(directory):
    d = Path(directory)
    threads = split_threads((d / "threads.txt").read_text(encoding="utf-8"))
    by_tid = {native_tid(t): t for t in threads}
    write_nr = WRITE_SYSCALL.get((d / "arch.txt").read_text().strip(), "1")
    kernel = read_tsv(d / "kernel.tsv", ["tid", "comm", "state", "wchan", "syscall"])
    hikari = dict(line.split("=") for line in (d / "hikari.txt").read_text().split())
    mysql = read_tsv(d / "mysql.tsv", ["kind", "id", "a", "b", "c"])

    pipe_write, log_lock, conn_wait = classify(threads)
    addr, waiting, owner = lock_owner(threads, log_lock)
    holders = [t for t in threads if is_holding_connection(t)]

    # [1] 커널
    writers = [k for k in kernel if k["syscall"].split()[:2] == [write_nr, "0x1"]]
    writer_tids = {int(k["tid"]) for k in writers}
    print("[1] 커널: stdout(fd 1)에 write 하다 잠든 스레드")
    if not writers:
        print("    없음 (파이프가 막히지 않은 상태)")
    for k in writers:
        block = by_tid.get(int(k["tid"]))
        name = thread_name(block) if block else k["comm"]
        jvm = jvm_state(block) if block else "?"
        print(f"    tid {k['tid']} \"{name}\"  커널 상태={k['state']}, 잠든 위치(wchan)={k['wchan']}"
              f"  ← JVM 스레드 덤프에서는 {jvm}")

    # [2] JVM 락
    print("\n[2] JVM: Logback 출력 락")
    if owner:
        same = "[1]의 스레드와 같다" if native_tid(owner) in writer_tids else "[1]의 스레드가 아니다"
        holding = sum(map(is_holding_connection, log_lock))
        failing = sum(is_logging_failure(t) and not is_holding_connection(t) for t in log_lock)
        print(f"    락 <{addr}> 주인: \"{thread_name(owner)}\" ({same})")
        print(f"    락 대기 {len(log_lock)}개: 커넥션 보유 {holding} / 타임아웃 뒤 실패 로그 {failing} / "
              f"기타 {len(log_lock) - holding - failing}")
    else:
        print("    락을 기다리는 스레드 없음")

    # [3] 커넥션
    print("\n[3] 커넥션 풀")
    print(f"    HikariCP: active={hikari['active']} idle={hikari['idle']} pending={hikari['pending']} "
          f"timeout누적={hikari['timeout']}")
    print(f"    덤프에서 커넥션을 쥔 스레드: {len(holders)}개 (write에서 잠든 {sum(map(is_holding_connection, pipe_write))}"
          f" + 락 대기 {sum(map(is_holding_connection, log_lock))} + 그 밖 "
          f"{len(holders) - sum(map(is_holding_connection, pipe_write + log_lock))})")
    print(f"    덤프에서 커넥션을 기다리는 스레드: {len(conn_wait)}개")

    # [4] MySQL
    trx = [r for r in mysql if r["kind"] == "trx"]
    conns = [r for r in mysql if r["kind"] == "conn"]
    running = sum(1 for r in trx if r["c"])
    oldest = max((int(r["a"]) for r in trx), default=0)
    print("\n[4] MySQL")
    print(f"    열린 트랜잭션 {len(trx)}개 (읽기 전용 {sum(r['b'] == '1' for r in trx)}), "
          f"쿼리 실행 중 {running}개, 가장 오래된 것 {oldest}초째")
    commands = Counter(r["a"] for r in conns)
    print(f"    앱 커넥션 {len(conns)}개: " + ", ".join(f"{cmd} {n}개" for cmd, n in commands.most_common()))

    # 맞춰 보기
    print("\n[맞춰 보기]")
    print(f"    커넥션 수: HikariCP active {hikari['active']} / 덤프의 커넥션 보유 스레드 {len(holders)} / "
          f"MySQL 열린 트랜잭션 {len(trx)}")
    if holders and running == 0:
        print("    MySQL에서 실행 중인 쿼리가 0개다. 커넥션을 쥔 스레드들은 DB가 아니라 로그 출력에서 멈춰 있다.")


if __name__ == "__main__":
    main(sys.argv[1])
