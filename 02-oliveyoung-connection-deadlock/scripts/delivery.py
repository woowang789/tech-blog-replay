"""4단계 실행기: 지금 떠 있는 앱 설정(알림 구조, 실패 주입) 그대로 알림 30건을 요청하고, 고객이 실제로 받은 알림톡을 센다.

앱이 클레임을 다 채울 때까지 기다린다 → 큐를 비운다 → 알림 30건 요청
→ 큐가 비고(처리 중인 메시지까지 0) 원장에 끝나지 않은 알림이 없을 때까지, 최대 90초 동안 0.5초마다 본다.
결과는 화면에 출력하고 results/delivery-<이름>.txt에도 남긴다.

  고객이 받은 알림   고객에게 나간 서로 다른 알림 수. 요청한 수보다 적으면 그만큼 유실이다
  보낸 알림톡       고객에게 실제로 나간 알림톡 수. 같은 알림이 두 번 나가면 두 번 센다.
                  고객이 받은 알림보다 많으면 그만큼 중복이다
  API 호출         Messaging API를 부른 수. 외부 API가 멱등 키로 걸러 낸 호출은 보낸 알림톡에 들어가지 않는다

사용법: python3 scripts/delivery.py <이름>
"""
import json
import os
import sys
import time
import urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path

from scenario import compose_exec, duration, ready, request

COUNT = 30
LIMIT_SECONDS = 90
SQS = "http://localhost:9324/000000000000/"
DESIGNS = {
    "article": ("올리브영 구조 (3단계 해결 ① 적용)", "notice-queue", "notices"),
    "ledger": ("권하는 구조 (알림 원장 + outbox + 멱등 소비자)", "notification-queue", "notifications"),
}
FAULTS = {
    "none": "없음",
    "publish": "발행",
    "after-send": "발송 뒤, 기록 전",
    "after-record": "기록 뒤, 메시지 삭제 전",
}


def deliveries():
    return json.loads(request("http://localhost:8080/experiments/deliveries"))


def purge_all():
    # 두 구조의 큐를 모두 비운다. 앞 실행이 남긴 메시지(실패해서 지우지 못한 메시지 등)가 이번 실행에 섞이지 않게 한다.
    # 권하는 구조를 한 번도 띄우지 않았으면 notification-queue가 없어서 그 오류는 넘긴다
    for _, queue, _ in DESIGNS.values():
        try:
            request(SQS + queue + "?Action=PurgeQueue")
        except urllib.error.HTTPError:
            pass


def messages_left(queue):
    # 처리를 기다리는 메시지와 처리 중인(아직 지우지 않은) 메시지를 더한다
    url = (SQS + queue + "?Action=GetQueueAttributes"
           "&AttributeName.1=ApproximateNumberOfMessages&AttributeName.2=ApproximateNumberOfMessagesNotVisible")
    root = ET.fromstring(request(url))
    return sum(int(value.text) for value in root.iter("{http://queue.amazonaws.com/doc/2012-11-05/}Value"))


def main(name):
    os.chdir(Path(__file__).resolve().parent.parent)
    for i in range(90):
        if ready():
            break
        if i == 0:
            print("앱이 뜰 때까지 기다린다...")
        time.sleep(2)

    design = compose_exec("app", "printenv", "REPLAY_NOTICEDESIGN")
    fault = compose_exec("app", "printenv", "REPLAY_FAULT")
    idempotency = compose_exec("app", "printenv", "REPLAY_PROVIDERIDEMPOTENCY") == "true"
    requires_new = compose_exec("app", "printenv", "REPLAY_HISTORYREQUIRESNEW") == "true"
    label, queue, endpoint = DESIGNS[design]

    purge_all()
    started = time.monotonic()
    request(f"http://localhost:8080/experiments/{endpoint}?count={COUNT}", method="POST")
    elapsed = None
    first_empty = None
    while time.monotonic() - started < LIMIT_SECONDS:
        time.sleep(0.5)
        unfinished = sum(n for status, n in deliveries().get("ledger", {}).items() if status != "SENT")
        if messages_left(queue) > 0 or unfinished > 0:
            first_empty = None
            continue
        # 메시지 삭제는 Spring Cloud AWS가 모았다가 하므로, 두 번 연속 비어 있어야 끝난 것으로 본다
        if first_empty is not None:
            elapsed = first_empty - started
            break
        first_empty = time.monotonic()

    result = deliveries()
    purge_all()
    delivered, customers = result["delivered"], result["customers"]
    if design == "article":
        label += ", 이력 저장 " + ("REQUIRES_NEW" if requires_new else "바깥 트랜잭션에 참여")
        key = "쓰지 않음"
    else:
        key = "지원함" if idempotency else "지원하지 않음"
    lines = [
        f"== {name} ({time.strftime('%H:%M:%S')})",
        f"구조: {label}",
        f"실패 주입: {FAULTS[fault]} ({result['faults']}번), 외부 API 멱등 키: {key}",
        f"요청한 알림 {COUNT}건 → 고객이 받은 알림 {customers}건 (유실 {COUNT - customers}건)",
        f"보낸 알림톡 {delivered}통 (중복 {delivered - customers}통), Messaging API 호출 {result['apiCalls']}번",
    ]
    if "ledger" in result:
        lines.append("원장: " + ", ".join(f"{status} {n}" for status, n in result["ledger"].items()))
    lines.append("걸린 시간: " + (f"{duration(elapsed)} (큐가 비고 끝나지 않은 알림이 없을 때까지)"
                               if elapsed is not None else f"{LIMIT_SECONDS}초 안에 끝나지 않음"))
    # 실패 주입은 30건 중 정확히 10번이다. 다르거나 요청보다 많이 받았으면 이번 실행이 아닌 메시지가 섞인 것이다
    expected_faults = 0 if fault == "none" else COUNT // 3
    if customers > COUNT or result["faults"] != expected_faults:
        lines.append(f"주의: 실패 주입이 {expected_faults}번이 아니거나 요청보다 많은 알림을 받았다. "
                     "다른 실행의 메시지가 섞였을 수 있으니 앱을 새로 띄워 다시 돌린다")
    print("\n".join(lines))
    Path("results").mkdir(exist_ok=True)
    Path(f"results/delivery-{name}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])
