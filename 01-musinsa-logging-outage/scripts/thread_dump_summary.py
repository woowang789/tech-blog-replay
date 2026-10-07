"""jcmd Thread.print -l 결과에서 스레드를 '어디서 멈췄는지' 기준으로 분류한다."""
import re
import sys
from collections import Counter


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


def thread_name(block):
    return block.split('"')[1]


def holding_connection(blocks):
    # 서비스 메서드 본문을 실행 중이면 이미 트랜잭션이 시작됐다 = 커넥션을 쥐고 있다
    return sum("ProductService.getProduct" in b for b in blocks)


def main(path):
    threads = split_threads(open(path, encoding="utf-8").read())

    pipe_write = [t for t in threads if "java.io.FileOutputStream.writeBytes" in t]
    log_lock = [t for t in threads
                if "OutputStreamAppender" in t and "parking to wait for" in t and "ReentrantLock" in t]
    conn_wait = [t for t in threads if "com.zaxxer.hikari.pool.HikariPool.getConnection" in t]

    print(f"전체 스레드 {len(threads)}개")
    print(f"  1) stdout write에서 멈춤 (파이프가 비기를 기다림) : {len(pipe_write):4d}개 (그중 커넥션 보유 {holding_connection(pipe_write)}개)")
    print(f"  2) 로그 출력 락 대기 (streamWriteLock)           : {len(log_lock):4d}개 (그중 커넥션 보유 {holding_connection(log_lock)}개)")
    print(f"  3) DB 커넥션 대기 (HikariPool.getConnection)     : {len(conn_wait):4d}개")

    # 락을 기다리는 스레드들이 가리키는 락 주소로 락의 주인을 찾는다
    waited = Counter()
    for t in log_lock:
        m = re.search(r"parking to wait for\s+<(0x[0-9a-f]+)>", t)
        if m:
            waited[m.group(1)] += 1
    for addr, count in waited.most_common(1):
        owners = [t for t in threads if f"- <{addr}> (a java.util.concurrent.locks.ReentrantLock" in t]
        if owners:
            owner = owners[0]
            where = "stdout write에서 멈춘 스레드" if owner in pipe_write else "다른 곳"
            print(f"\n로그 락 <{addr}>: {count}개 스레드가 대기 중, 락 주인은 '{thread_name(owner)}' ({where})")

    if pipe_write:
        print("\n[예시] stdout write에서 멈춘 스레드의 스택 상위 부분")
        print("\n".join(pipe_write[0].splitlines()[:16]))


if __name__ == "__main__":
    main(sys.argv[1])
