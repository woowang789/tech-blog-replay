#!/bin/sh
# 컨테이너 런타임과 로그 수집기를 흉내 낸다.
#   앱 stdout → 커널 파이프 버퍼(약 64KB) → pv(수집기) → 컨테이너 stdout(docker logs)
# pv는 LOG_CONSUMER_RATE(바이트/초)만큼만 읽는다. 수집기가 로그 발생량을 못 따라가는 상황을 만드는 손잡이다.
# stderr는 파이프를 거치지 않고 바로 docker logs로 간다.
java ${JAVA_OPTS} -jar /app/app.jar | pv --quiet --buffer-size 4k --rate-limit "${LOG_CONSUMER_RATE}"
