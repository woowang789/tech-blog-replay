"""2단계 실행기: 1단계와 같은 조건(조회 초당 200건, 20초째에 전체 삭제 1번)을 돌리면서, 조회가 멈춘 동안
Redis, 앱의 Redis 연결, 앱 JVM에서 무슨 일이 있었는지 증거를 함께 모아 같은 시간축에 놓는다.

앞 실행이 남긴 것을 치운다(Redis를 비우고 products 캐시 N개와, 주면 다른 캐시 others M개를 채운다) → 앱을 데운다
→ SLOWLOG와 명령 통계를 비운다 → 수집기를 켜고 k6/load.js를 돌린다 → 증거를 모아 요약한다.
결과는 화면에 출력하고 results/evidence-<이름>/에도 남긴다.
  k6.csv, k6-summary.txt   1단계와 같다
  probe.csv                수집기가 Redis에 보낸 CLIENT LIST의 왕복 시간과, 그때 본 앱 연결의 상태
  slowlog.json             Redis가 10ms 넘게 실행한 명령
  gc.log                   앱 GC 로그
  thread-dumps.txt         앱 스레드 덤프 원문
  report.txt               화면에 출력한 요약

증거 (시각은 모두 전체 삭제를 보낸 때가 0)
  조회           k6. 1단계와 같다
  Redis 멈춤      수집기가 앱과 따로 연 연결로 5ms마다 CLIENT LIST를 보낸다. 답이 50ms 넘게 늦으면 그동안
                 Redis가 다른 일에 붙잡혀 명령을 처리하지 못한 것으로 본다
  GC 멈춤        앱 GC 로그의 멈춤(Pause, 10ms 이상). 그동안 앱의 모든 스레드가 선다
  앱 연결         CLIENT LIST로 본 앱의 Redis 연결. 삭제 전에 명령이 가장 많이 오간 연결이 조회 연결이고,
                 전체 삭제의 명령이 오간 연결이 삭제 연결이다(동기면 둘이 같다)
    명령          그 0.1초 동안 Redis가 그 연결에서 처리한 명령 수(tot-cmds가 는 만큼)
    보낼 응답      Redis가 그 연결로 아직 다 보내지 못한 응답의 크기(omem)
    받는 명령      Redis가 그 연결에서 받고 있거나 받아 놓고 아직 끝내지 못한 명령의 크기(qbuf + argv-mem)
  스레드 덤프     전체 삭제로 Redis가 처음 멈춘 것이 보이면 0.5초마다 12번 뜬다. 전체 삭제를 부른 요청 스레드와,
                 쉬지 않고 일하던 Lettuce I/O 스레드가 무엇을 하고 있었는지 본다. 앱에 SIGQUIT(kill -3)을 보내
                 앱이 스스로 표준 출력에 찍게 한다. jcmd처럼 새 JVM을 띄우지 않아 실험을 덜 흔든다

사용법: python3 scripts/evidence.py <이름> [products 캐시 키 수, 기본 1000000] [others 캐시 키 수, 기본 0]
"""
import json
import math
import os
import re
import socket
import subprocess
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from scenario import (EVICT_AT_SECONDS, HOT, RATE, SLOW_MS, WARMUP_SECONDS, checks, command_calls, compose_exec, fmt,
                      load, ready, redis, request, run_k6, stalls)

PROBE_INTERVAL = 0.005
REDIS_STUCK_MS = 50
GC_MIN_MS = 10
BIG_BYTES = 1024 * 1024
BUSY_COMMANDS = 100
DUMP_INTERVAL = 0.5
DUMP_COUNT = 12
ZOOM_LIMIT_SECONDS = 12
GC_PAUSE = re.compile(r"\[([^\]]+)\]\[[^\]]+\] GC\(\d+\) (Pause .*?) (\d+(?:\.\d+)?)ms$")
MORE_ARGS = re.compile(r"\.\.\. \((\d+) more arguments\)")
FRAME = re.compile(r"^\s+at ([\w$.]+)\.([\w$<>]+)\(")
KEY_COMMANDS = ["org.springframework.data.redis.connection.lettuce.LettuceKeyCommands", "org.springframework.data.redis"]


class Probe(threading.Thread):
    # 앱과 따로 Redis에 연결해 5ms마다 CLIENT LIST를 보내고, 왕복 시간과 앱 연결(Lettuce)의 상태를 남긴다.
    # 전체 삭제 무렵(k6 시작 15초 뒤부터) Redis가 처음 멈춘 것이 보이면 스레드 덤프를 시작시킨다
    COMMAND = b"*4\r\n$6\r\nCLIENT\r\n$4\r\nLIST\r\n$4\r\nTYPE\r\n$6\r\nnormal\r\n"

    def __init__(self, sock, dumper):
        super().__init__(daemon=True)
        self.sock = sock
        self.dumper = dumper
        self.samples = []
        self.done = threading.Event()
        self.watch_from = float("inf")

    def run(self):
        reader = self.sock.makefile("rb")
        while not self.done.is_set():
            sent = time.time()
            self.sock.sendall(self.COMMAND)
            size = int(reader.readline()[1:])
            body = reader.read(size + 2).decode()
            received = time.time()
            self.samples.append((sent, received, app_connections(body)))
            if received - sent > REDIS_STUCK_MS / 1000 and sent > self.watch_from:
                self.dumper.trigger.set()
            time.sleep(max(0.0, PROBE_INTERVAL - (received - sent)))


class Dumper(threading.Thread):
    # 시작 신호를 받으면 0.5초마다 앱(PID 1)에 SIGQUIT을 보낸다. 덤프는 앱 로그에 찍히고 실행이 끝난 뒤 모은다
    def __init__(self):
        super().__init__(daemon=True)
        self.trigger = threading.Event()
        self.done = threading.Event()
        self.sent = 0

    def run(self):
        while not self.trigger.wait(0.1):
            if self.done.is_set():
                return
        while not self.done.is_set() and self.sent < DUMP_COUNT:
            started = time.time()
            compose_exec("app", "kill", "-3", "1")
            self.sent += 1
            time.sleep(max(0.0, DUMP_INTERVAL - (time.time() - started)))


def app_connections(client_list):
    # CLIENT LIST 한 줄이 연결 하나다. 앱(Lettuce)의 연결만 골라 필요한 값만 남긴다
    connections = {}
    for line in client_list.splitlines():
        fields = dict(item.split("=", 1) for item in line.split(" ") if "=" in item)
        if fields.get("lib-name", "").startswith("Lettuce"):
            connections[fields["id"]] = {
                "addr": fields["addr"],
                "out": int(fields["omem"]),
                "in": int(fields["qbuf"]) + int(fields["argv-mem"]),
                "cmds": int(fields["tot-cmds"]),
            }
    return connections


def gc_pauses(text):
    # "[2026-10-13T03:44:06.670+0000][170.659s] GC(66) Pause Young (Normal) (G1 Evacuation Pause) ... 26.982ms"
    pauses = []
    for line in text.splitlines():
        m = GC_PAUSE.match(line.strip())
        if m and float(m.group(3)) >= GC_MIN_MS:
            end = datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S.%f%z").timestamp()
            took = float(m.group(3)) / 1000
            pauses.append((end - took, end, took, m.group(2)))
    return pauses


def parse_stamp(stamp):
    # docker logs --timestamps의 RFC3339Nano 시각. 소수점 아래는 9자리까지이고 뒤의 0은 빠질 수 있다
    whole, _, fraction = stamp.rstrip("Z").partition(".")
    seconds = datetime.strptime(whole, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    return seconds + float("0." + (fraction or "0"))


def thread_dumps(log_text):
    # 앱 로그에서 SIGQUIT 스레드 덤프를 꺼낸다. "Full thread dump"로 시작해 "JNI global refs"에서 끝난다
    dumps, current, at = [], None, None
    for line in log_text.splitlines():
        stamp, _, content = line.partition(" ")
        if content.startswith("Full thread dump"):
            current, at = [], parse_stamp(stamp)
        elif current is not None:
            if content.startswith("JNI global refs"):
                dumps.append((at, "\n".join(current)))
                current = None
            else:
                current.append(content)
    return dumps


def threads(dump):
    # 스레드 덤프를 스레드마다 (이름, 상태, 프레임 목록)으로 나눈다
    found = []
    for block in dump.split("\n\n"):
        lines = block.strip().splitlines()
        if not lines or not lines[0].startswith('"'):
            continue
        state = next((l.split(":", 1)[1].strip() for l in lines if "java.lang.Thread.State" in l), "")
        frames = [f"{m.group(1).rsplit('.', 1)[-1]}.{m.group(2)}" for m in map(FRAME.match, lines) if m]
        full = [m.group(1) for m in map(FRAME.match, lines) if m]
        found.append((lines[0].split('"')[1], state.split(" ")[0], frames, full))
    return found


def describe_thread(frames, full, packages):
    # 맨 위 프레임 두 개와, 그 아래에서 처음 나오는 packages의 프레임(앞에 둔 것부터 찾는다)
    shown = frames[:2]
    deeper = next((frames[i] for package in packages for i, cls in enumerate(full)
                   if i >= 2 and cls.startswith(package)), None)
    return " ← ".join(shown + (["…", deeper] if deeper else []))


def describe_dump(dump):
    evict, busy = None, []
    for name, state, frames, full in threads(dump):
        if any(f.endswith(".evictAll") for f in frames):
            # 어느 Redis 명령(keys, del) 단계인지 보이게 LettuceKeyCommands 프레임을 먼저 찾는다
            evict = f"{state} {describe_thread(frames, full, KEY_COMMANDS)}"
        elif name.startswith("lettuce-") and "EventLoop" in name and frames and frames[0] != "EPoll.wait":
            busy.append(f"{name} {describe_thread(frames, full, ['io.lettuce'])}")
    return evict, busy


def merge(spans, gap):
    # 구간들을 gap보다 가까우면 하나로 잇는다
    merged = []
    for start, end in sorted(spans):
        if merged and start - merged[-1][1] <= gap:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def overlapping(spans, start, end):
    return [s for s in spans if s[0] <= end and s[1] >= start]


def describe_spans(spans):
    if not spans:
        return "없음"
    return ", ".join(f"{s:+.2f}~{e:+.2f}초({fmt(e - s)})" for s, e in spans)


def covered_ms(spans, tick):
    # 0.1초 칸 하나 중 구간들이 덮은 시간(ms)
    start, end = tick / 10, (tick + 1) / 10
    return sum(max(0.0, min(e, end) - max(s, start)) for s, e in spans) * 1000


def describe_command(args):
    # SLOWLOG는 인자를 32개까지만 남기고 마지막에 "... (N more arguments)"를 붙인다. 키를 여러 개 받는 삭제 명령만 키 수로 보인다
    if args[0].upper() not in ("DEL", "UNLINK"):
        return " ".join(args[:2])
    more = MORE_ARGS.match(args[-1])
    keys = 30 + int(more.group(1)) if more else len(args) - 1
    return f"{args[0].upper()} 키 {keys:,}개"


def connection_series(probe, connection):
    # 0.1초 칸마다 (처리한 명령 수, 보낼 응답 최대, 받는 명령 최대)
    cmds, out, inn = defaultdict(int), defaultdict(int), defaultdict(int)
    previous = None
    for _, received, connections in probe:
        state = connections.get(connection)
        if state is None:
            continue
        tick = math.floor(received * 10)
        if previous is not None:
            cmds[tick] += state["cmds"] - previous
        previous = state["cmds"]
        out[tick] = max(out[tick], state["out"])
        inn[tick] = max(inn[tick], state["in"])
    return cmds, out, inn


def report(name, immediate, count, others, keys_before, calls, reads, evicts, dropped, samples, slowlog, pauses, dumps):
    mode = "원문처럼 동기" if immediate else "4.x 기본(비동기)"
    crowd = f" + others 캐시 키 {others:,}개" if others else ""
    lines = [
        f"== {name} ({time.strftime('%H:%M:%S')})",
        f"설정: 캐시 쓰기 {mode}, products 캐시 키 {count:,}개{crowd}",
        f"      조회 초당 {RATE}건(인기 상품 {HOT:,}개 중 하나), 부하 {EVICT_AT_SECONDS}초째에 전체 삭제 1번",
        f"Redis가 받은 명령: KEYS {calls.get('keys', 0)}번, DEL {calls.get('del', 0)}번, UNLINK {calls.get('unlink', 0):,}번"
        f" (삭제 전 키 {keys_before:,}개)",
    ]
    lines += checks(immediate, count + others, keys_before, calls, evicts, dropped)
    if not evicts or not samples:
        return lines + ["주의: 전체 삭제 기록이나 수집기 기록이 없다"]

    evict_start, _, evict_took, _ = evicts[0]
    since = WARMUP_SECONDS - EVICT_AT_SECONDS
    rel = [(start - evict_start, end - evict_start, took, status) for start, end, took, status in reads
           if start - evict_start >= since]
    probe = [(sent - evict_start, received - evict_start, connections) for sent, received, connections in samples]
    pauses = [(start - evict_start, end - evict_start, took, what) for start, end, took, what in pauses]

    # 삭제 전에 명령이 가장 많이 오간 연결이 조회 연결이다. 비동기면 남은 앱 연결이 삭제 연결이다
    before = [connections for sent, _, connections in probe if sent < 0]
    read_conn = max(before[-1], key=lambda c: before[-1][c]["cmds"] - before[0].get(c, {"cmds": 0})["cmds"])
    other_conns = [c for c in before[-1] if c != read_conn]
    delete_conn = read_conn if immediate else (other_conns[0] if len(other_conns) == 1 else None)
    names = {read_conn: "조회 연결"}
    if delete_conn and delete_conn != read_conn:
        names[delete_conn] = "삭제 연결"
    addrs = {state["addr"]: names.get(c, f"다른 연결 id={c}") for c, state in before[-1].items()}

    stuck = merge([(sent, received) for sent, received, _ in probe if received - sent > REDIS_STUCK_MS / 1000], 0.02)
    gc_spans = [(start, end) for start, end, _, _ in pauses]

    def big(connection, key):
        points = [(received, received) for _, received, connections in probe
                  if connection in connections and connections[connection][key] > BIG_BYTES]
        return merge(points, 0.05)

    lines += [
        f"전체 삭제: 보내고 {fmt(evict_took)} 만에 응답",
        "",
        f"조회가 멈췄다가 한꺼번에 풀린 때와 그동안의 증거 ({SLOW_MS}ms 넘게 기다린 조회를 이어 붙였다)",
    ]
    found = stalls(rel)
    if not found:
        lines.append("  없음")
    for start, end, n, peak in found:
        lines += [
            f"  {start:+.2f}초 ~ {end:+.2f}초  조회 {n}건이 {SLOW_MS}ms 넘게 기다림, 최대 {fmt(peak)}",
            f"    Redis 멈춤                     {describe_spans(overlapping(stuck, start, end))}",
            f"    GC 멈춤                        {describe_spans(overlapping(gc_spans, start, end))}",
            f"    조회 연결에 보낼 응답 1MB 넘음    {describe_spans(overlapping(big(read_conn, 'out'), start, end))}",
            f"    조회 연결에 받는 명령 1MB 넘음    {describe_spans(overlapping(big(read_conn, 'in'), start, end))}",
        ]

    # 같은 연결에서 온 같은 모양의 명령이 이어지면 한 줄로 묶는다
    lines += ["", "Redis가 10ms 넘게 실행한 명령 (SLOWLOG)"]
    groups = []
    for entry in sorted(slowlog, key=lambda e: e[0]):
        _, logged, micros, args, addr = entry[:5]
        key = (describe_command(args), addrs.get(addr, "수집기" if args[0].upper() == "CLIENT" else addr))
        if groups and groups[-1][0] == key:
            groups[-1][1].append((logged, micros))
        else:
            groups.append((key, [(logged, micros)]))
    for (command, connection), entries in groups:
        micros = [m for _, m in entries]
        when = sorted({datetime.fromtimestamp(t).strftime("%H:%M:%S") for t, _ in entries})
        took = fmt(micros[0] / 1_000_000) if len(entries) == 1 else \
            f"{len(entries)}번 {fmt(min(micros) / 1_000_000)}~{fmt(max(micros) / 1_000_000)}"
        ended = when[0] if len(when) == 1 else f"{when[0]}~{when[-1]}"
        lines.append(f"  {command:<26} {took:>12}  {connection}  ({ended}에 끝남)")
    if not slowlog:
        lines.append("  없음")

    shown = [p for p in pauses if -1 <= p[0] <= 10]
    lines += ["", f"앱 GC 멈춤 (삭제 -1초 ~ +10초, {GC_MIN_MS}ms 이상)"]
    lines += [f"  {start:+.2f}초  {fmt(took):>6}  {what}" for start, _, took, what in shown] or ["  없음"]

    lines += ["", f"앱 스레드 덤프 (전체 삭제로 Redis가 처음 멈춘 것이 보인 뒤 {DUMP_INTERVAL}초마다)"]
    for at, text in dumps:
        evict, busy = describe_dump(text)
        lines.append(f"  {at - evict_start:+.2f}초  전체 삭제 요청 스레드: {evict or '없음 (이미 응답함)'}")
        lines += [f"          바쁜 Lettuce I/O 스레드: {b}" for b in busy] or ["          바쁜 Lettuce I/O 스레드: 없음"]
    if not dumps:
        lines.append("  없음 (Redis가 멈춘 것이 보이지 않았다)")

    busy_end = 0
    if delete_conn and delete_conn != read_conn:
        cmds, _, _ = connection_series(probe, delete_conn)
        busy = [t for t, n in cmds.items() if t >= 0 and n > BUSY_COMMANDS]
        if busy:
            busy_end = (max(busy) + 1) / 10
            total = sum(n for t, n in cmds.items() if min(busy) <= t <= max(busy))
            lines += ["", f"삭제 연결에서 명령이 0.1초에 {BUSY_COMMANDS}개 넘게 처리된 구간: "
                          f"{min(busy) / 10:+.1f}~{busy_end:+.1f}초 (그동안 {total:,}개)"]

    # 0.1초 단위 표: 전체 삭제 응답(빨라도 2.5초로 친다)과 그 무렵까지 시작한 멈춤이 끝난 뒤 0.3초까지.
    # 비동기에서 UNLINK가 도는 구간은 길어서 표 대신 위의 한 줄로 본다
    last = max(evict_took, 2.5)
    until = min(max([last] + [end for start, end, _, _ in found if start <= last + 0.5]) + 0.3, ZOOM_LIMIT_SECONDS)
    sent, done = defaultdict(list), defaultdict(int)
    for start, end, took, _ in rel:
        sent[math.floor(start * 10)].append(took)
        done[math.floor(end * 10)] += 1
    series = {c: connection_series(probe, c) for c in names}
    head = "    시각(초)   조회 끝남  최대 응답 | Redis 멈춤  GC 멈춤 | 조회 연결: 명령  보낼 응답  받는 명령"
    if len(names) > 1:
        head += " | 삭제 연결: 명령  보낼 응답  받는 명령"
    lines += ["", "삭제 전후 0.1초 단위 (멈춤은 그 0.1초 중 멈춘 ms, 응답·명령 크기는 MB. 같은 모양이 이어지는 줄은 접었다)",
              head]
    rows = []
    for tick in range(-3, math.ceil(until * 10)):
        values = sent.get(tick, [])
        shape = [done.get(tick, 0), round(covered_ms(stuck, tick)), round(covered_ms(gc_spans, tick))]
        row = (f"  {f'{tick / 10:+.1f}~{(tick + 1) / 10:+.1f}':>10}  {shape[0]:>8}  {fmt(max(values)) if values else '-':>8}"
               f" | {shape[1]:>8}  {shape[2]:>7}")
        for connection in names:
            cmds, out, inn = series[connection]
            parts = [cmds.get(tick, 0), round(out.get(tick, 0) / BIG_BYTES, 1), round(inn.get(tick, 0) / BIG_BYTES, 1)]
            shape += parts
            row += f" | {parts[0]:>15,}  {parts[1]:>9.1f}  {parts[2]:>9.1f}"
        marks = []
        if tick == 0:
            marks.append("◀ 전체 삭제를 보냄")
        if tick == math.floor(evict_took * 10):
            marks.append("◀ 전체 삭제 응답")
        rows.append((tuple(shape), marks, row + "".join(f"  {m}" for m in marks)))
    i = 0
    while i < len(rows):
        j = i
        while j + 1 < len(rows) and rows[j + 1][0] == rows[i][0] and not rows[j + 1][1]:
            j += 1
        if j - i >= 3:
            lines += [rows[i][2], f"  {'⋮':>10}  (같은 모양 {j - i - 1}줄)", rows[j][2]]
        else:
            lines += [r[2] for r in rows[i:j + 1]]
        i = j + 1
    return lines


def main(name, count, others):
    os.chdir(Path(__file__).resolve().parent.parent)
    for i in range(90):
        if ready():
            break
        if i == 0:
            print("앱이 뜰 때까지 기다린다...")
        time.sleep(2)
    immediate = compose_exec("app", "printenv", "REPLAY_CACHEIMMEDIATEWRITES") == "true"
    try:
        sock = socket.create_connection(("localhost", 6379), timeout=5)
    except OSError:
        sys.exit("Redis 6379 포트에 연결할 수 없다. 2단계 준비대로 docker compose up -d로 다시 띄운다")
    sock.settimeout(None)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    # 앞 실행이 남긴 것을 치운다. 1단계 실행기와 같다
    crowd = f", others 캐시 {others:,}개" if others else ""
    print(f"Redis를 비우고 products 캐시를 {count:,}개{crowd}로 채운다...")
    redis("FLUSHALL")
    request(f"http://localhost:8080/experiments/seed?count={count}", method="POST", timeout=600)
    if others:
        request(f"http://localhost:8080/experiments/seed?count={others}&cache=others", method="POST", timeout=600)
    print(f"인기 상품 {HOT:,}개를 한 번씩 조회해 앱을 데운다...")
    for product_id in range(1, HOT + 1):
        request(f"http://localhost:8080/products/{product_id}")
    keys_before = int(redis("DBSIZE"))
    redis("SLOWLOG", "RESET")
    redis("CONFIG", "RESETSTAT")

    out = Path(f"results/evidence-{name}")
    out.mkdir(parents=True, exist_ok=True)
    dumper = Dumper()
    probe = Probe(sock, dumper)
    probe.watch_from = time.time() + EVICT_AT_SECONDS - 5
    dumper.start()
    probe.start()
    print(f"k6: 조회 초당 {RATE}건, {EVICT_AT_SECONDS}초째에 전체 삭제 1번. 수집기가 5ms마다 Redis를 본다...")
    k6_started = time.time()
    run_k6(out)
    probe.done.set()
    dumper.done.set()
    probe.join()
    dumper.join()
    sock.close()

    calls = command_calls()
    slowlog = json.loads(compose_exec("redis", "redis-cli", "--json", "SLOWLOG", "GET", "128"))
    gc_text = compose_exec("app", "cat", "/tmp/gc.log")
    since = datetime.fromtimestamp(k6_started - 1, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    app_log = subprocess.run(["docker", "compose", "logs", "app", "--no-log-prefix", "--timestamps", "--since", since],
                             capture_output=True, text=True).stdout
    dumps = thread_dumps(app_log)
    reads, evicts, dropped = load(out / "k6.csv")
    (out / "slowlog.json").write_text(json.dumps(slowlog, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "gc.log").write_text(gc_text + "\n", encoding="utf-8")
    with open(out / "thread-dumps.txt", "w", encoding="utf-8") as f:
        for at, text in dumps:
            f.write(f"===== {datetime.fromtimestamp(at).strftime('%H:%M:%S.%f')[:-3]}\n{text}\n\n")
    with open(out / "probe.csv", "w", encoding="utf-8") as f:
        f.write("sent,received,id,addr,omem,qbuf_argv,tot_cmds\n")
        for sent, received, connections in probe.samples:
            for c, s in connections.items():
                f.write(f"{sent:.6f},{received:.6f},{c},{s['addr']},{s['out']},{s['in']},{s['cmds']}\n")

    lines = report(name, immediate, count, others, keys_before, calls, reads, evicts, dropped, probe.samples, slowlog,
                   gc_pauses(gc_text), dumps)
    print("\n".join(lines))
    (out / "report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 1_000_000, int(sys.argv[3]) if len(sys.argv) > 3 else 0)
