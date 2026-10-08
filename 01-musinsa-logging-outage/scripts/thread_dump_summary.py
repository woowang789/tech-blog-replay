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


def native_tid(block):
    # 헤더의 nid는 커널이 보는 스레드 ID(tid)다. JDK 버전에 따라 10진수 또는 16진수로 찍힌다
    m = re.search(r"\bnid=(0x[0-9a-f]+|\d+)", block.splitlines()[0])
    return int(m.group(1), 0) if m else None


def jvm_state(block):
    m = re.search(r"java\.lang\.Thread\.State: (\S+)", block)
    return m.group(1) if m else "?"


def is_holding_connection(block):
    # 서비스 메서드 본문을 실행 중이면 이미 트랜잭션이 시작됐다 = 커넥션을 쥐고 있다
    return "ProductService.getProduct" in block


def is_logging_failure(block):
    # 커넥션 획득이 타임아웃된 뒤 실패를 로그로 남기는 중 (Hibernate SqlExceptionHelper 또는 예외 핸들러)
    return "SqlExceptionHelper" in block or "GlobalExceptionHandler" in block


def classify(threads):
    pipe_write = [t for t in threads if "java.io.FileOutputStream.writeBytes" in t]
    log_lock = [t for t in threads
                if "OutputStreamAppender" in t and "parking to wait for" in t and "ReentrantLock" in t]
    conn_wait = [t for t in threads if "com.zaxxer.hikari.pool.HikariPool.getConnection" in t]
    return pipe_write, log_lock, conn_wait


def lock_owner(threads, log_lock):
    # 락을 기다리는 스레드들이 가리키는 락 주소로 락의 주인을 찾는다
    waited = Counter()
    for t in log_lock:
        m = re.search(r"parking to wait for\s+<(0x[0-9a-f]+)>", t)
        if m:
            waited[m.group(1)] += 1
    for addr, count in waited.most_common(1):
        owners = [t for t in threads if f"- <{addr}> (a java.util.concurrent.locks.ReentrantLock" in t]
        return addr, count, (owners[0] if owners else None)
    return None, 0, None


def main(path):
    threads = split_threads(open(path, encoding="utf-8").read())
    pipe_write, log_lock, conn_wait = classify(threads)
    holding = sum(map(is_holding_connection, log_lock))
    failing = sum(is_logging_failure(t) and not is_holding_connection(t) for t in log_lock)

    print(f"전체 스레드 {len(threads)}개")
    print(f"  1) stdout write에서 멈춤 (파이프가 비기를 기다림) : {len(pipe_write):4d}개 "
          f"(그중 커넥션 보유 {sum(map(is_holding_connection, pipe_write))}개)")
    print(f"  2) 로그 출력 락 대기 (streamWriteLock)           : {len(log_lock):4d}개 "
          f"(커넥션 보유 {holding}개, 타임아웃 뒤 실패 로그 {failing}개, 기타 {len(log_lock) - holding - failing}개)")
    print(f"  3) DB 커넥션 대기 (HikariPool.getConnection)     : {len(conn_wait):4d}개")

    addr, count, owner = lock_owner(threads, log_lock)
    if owner:
        where = "stdout write에서 멈춘 스레드" if owner in pipe_write else "다른 곳"
        print(f"\n로그 락 <{addr}>: {count}개 스레드가 대기 중, 락 주인은 '{thread_name(owner)}' ({where})")

    if pipe_write:
        print("\n[예시] stdout write에서 멈춘 스레드의 스택 상위 부분")
        print("\n".join(pipe_write[0].splitlines()[:16]))


if __name__ == "__main__":
    main(sys.argv[1])
