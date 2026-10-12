#!/usr/bin/env bash
# 로컬 SQS(ElasticMQ)의 알림 큐를 보거나 비운다.
#   status : 처리를 기다리는 메시지 수, 처리 중인 메시지 수, 가시성 타임아웃
#   purge  : 큐의 메시지를 모두 지운다. 실험 사이에 초기화할 때 쓴다
# ElasticMQ는 서명 없는 SQS API 요청도 받아서 curl로 바로 부른다.
set -euo pipefail

QUEUE_URL="localhost:9324/000000000000/notice-queue"

case "${1:-}" in
	status)
		curl -sf "$QUEUE_URL?Action=GetQueueAttributes&AttributeName.1=All" | python3 -c '
import sys, xml.etree.ElementTree as ET
ns = {"q": "http://queue.amazonaws.com/doc/2012-11-05/"}
attrs = {a.find("q:Name", ns).text: a.find("q:Value", ns).text for a in ET.parse(sys.stdin).iter("{%s}Attribute" % ns["q"])}
print("처리를 기다리는 메시지:", attrs["ApproximateNumberOfMessages"])
print("처리 중인 메시지:      ", attrs["ApproximateNumberOfMessagesNotVisible"])
print("가시성 타임아웃(초):   ", attrs["VisibilityTimeout"])
'
		;;
	purge)
		curl -sf "$QUEUE_URL?Action=PurgeQueue" > /dev/null
		echo "큐를 비웠다 ($(date +%H:%M:%S))"
		;;
	*) echo "usage: $0 status|purge" >&2; exit 1 ;;
esac
