FROM eclipse-temurin:21-jdk

# pv: 로그 수집기 역할(읽기 속도 제한), procps: pgrep/pkill
RUN apt-get update \
	&& apt-get install -y --no-install-recommends pv procps \
	&& rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY build/libs/app.jar app.jar
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
