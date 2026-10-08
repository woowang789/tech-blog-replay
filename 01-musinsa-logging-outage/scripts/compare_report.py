"""3단계 실행기(scenario.sh)의 결과를 요약한다. 결과 디렉터리를 여러 개 주면 한 표로 비교한다.

  DEBUG 동안 성공/초  장애 원인(DEBUG, 4-B는 에러 로그 폭주)을 켠 60초 동안 끝난 성공 응답 수 ÷ 60. 부하는 초당 50건이다
  503                k6가 받은 503 응답 수
  서버 503           앱이 만든 503 수 (앱 로그의 커넥션 획득 실패 줄). 실패 로그가 막혀 k6가 기다림을 멈춘 뒤에 나간 503은 k6 쪽에 잡히지 않는다
  회복               DEBUG를 끈 뒤, 1초 넘게 걸린 응답이 마지막으로 끝나기까지 걸린 시간
  로그 이벤트         앱이 남기려 한 로그 수 (Logback의 logback.events 메트릭이 늘어난 양)
  출력된 줄           그중 수집기를 지나 실제로 출력된 줄 수 (docker logs)
  버림               1 - 출력된 줄 ÷ 로그 이벤트
  trace_id 빈 줄      출력된 요청 스레드 로그 중 trace_id가 빈 줄 / trace_id 칸이 있는 줄

사용법: python3 scripts/compare_report.py results/compare-sync results/compare-trace-aware ...
"""
import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path

SLOW_MS = 1000
LOG_LINE = re.compile(r"^\d{4}-\d{2}-\d{2}T")  # Logback이 찍은 줄의 첫머리. 스택 트레이스의 이어지는 줄은 세지 않는다
REQUEST_THREAD = re.compile(r"-8080-exec-|handler-\d")  # Tomcat 요청 스레드. 가상 스레드(4-A)는 tomcat-handler-N
TRIGGER_LABEL = {"debug": "DEBUG 동안 성공/초", "error": "에러 폭주 동안 성공/초"}
TRACE_ID = re.compile(r"trace_id=(\S*)")
SERVER_503 = "DB 커넥션 획득 실패"  # GlobalExceptionHandler가 503을 만들기 직전에 남기는 로그


def p95(values):
    s = sorted(values)
    return s[min(len(s) - 1, round(0.95 * (len(s) - 1)))]


def duration(ms):
    return f"{ms:.0f}ms" if ms < 1000 else f"{ms / 1000:.1f}s"


def read_meta(path):
    meta = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep:
            meta[key] = value
    return meta


def summarize(directory):
    d = Path(directory)
    meta = read_meta(d / "meta.txt")
    on, off = int(meta["debug_on"]), int(meta["debug_off"])

    ok_during = failed_503 = 0
    durations = []
    last_slow = None
    with open(d / "k6.csv", newline="") as f:
        for row in csv.DictReader(f):
            if row["metric_name"] != "http_req_duration":
                continue
            ts, ms, status = int(float(row["timestamp"])), float(row["metric_value"]), row["status"]
            durations.append(ms)
            if ms > SLOW_MS:
                last_slow = ts if last_slow is None else max(last_slow, ts)
            if status == "200" and on <= ts < off:
                ok_during += 1
            elif status == "503":
                failed_503 += 1

    # Docker가 받은 시각이 아니라 로그에 찍힌 시각으로 고른다. 버퍼에 머물다 늦게 나온 앞선 로그를 빼기 위해서다
    start = float(meta["start"])
    printed = request_lines = empty_trace = server_503 = 0
    with open(d / "app.log", encoding="utf-8", errors="replace") as f:
        for line in f:
            if not LOG_LINE.match(line):
                continue
            if datetime.strptime(line.split(" ", 1)[0], "%Y-%m-%dT%H:%M:%S.%f%z").timestamp() < start:
                continue
            printed += 1
            if SERVER_503 in line:
                server_503 += 1
            match = TRACE_ID.search(line) if REQUEST_THREAD.search(line) else None
            if match:
                request_lines += 1
                if match.group(1) == "":
                    empty_trace += 1
    # 앱이 뜨기 전에 시작한 실행은 이벤트 수를 못 읽어 "?"로 남는다. 그때는 버림을 계산하지 않는다
    before, after = meta.get("events_before", "?"), meta.get("events_after", "?")
    produced = int(after) - int(before) if before.isdigit() and after.isdigit() else None

    return {
        "meta": meta,
        "이름": meta["name"],
        "원인 동안 성공/초": f"{ok_during / (off - on):.1f}",
        "503": str(failed_503),
        "서버 503": str(server_503),
        "p95": duration(p95(durations)) if durations else "-",
        "최대": duration(max(durations)) if durations else "-",
        "회복": f"{max(0, last_slow - off)}초" if last_slow is not None else "-",
        "로그 이벤트": f"{produced:,}" if produced is not None else "-",
        "출력된 줄": f"{printed:,}",
        "버림": f"{(1 - printed / produced) * 100:.1f}%" if produced else "-",
        "trace_id 빈 줄": f"{empty_trace}/{request_lines}" if request_lines else "-",
    }


def main(directories):
    rows = [summarize(d) for d in directories]
    if len(rows) == 1:
        meta = rows[0]["meta"]
        print(f"출력 설정: {json.dumps(json.loads(meta['logging']), ensure_ascii=False)}")
        print(f"환경 변수: {' '.join(f'{k}={v}' for k, v in meta.items() if k.isupper())}")
        print()
    columns = [c for c in rows[0] if c != "meta"]
    triggers = {r["meta"].get("trigger", "debug") for r in rows}
    label = TRIGGER_LABEL[triggers.pop()] if len(triggers) == 1 else "원인을 켠 동안 성공/초"
    print("| " + " | ".join(label if c == "원인 동안 성공/초" else c for c in columns) + " |")
    print("|" + "---|" * len(columns))
    for r in rows:
        print("| " + " | ".join(r[c] for c in columns) + " |")


if __name__ == "__main__":
    main(sys.argv[1:])
