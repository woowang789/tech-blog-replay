# jcmd로 스레드 덤프를 뜰 수 있게 JRE가 아니라 JDK 이미지를 쓴다. java가 PID 1이라 `jcmd 1 Thread.print`로 뜬다
FROM eclipse-temurin:21-jdk

WORKDIR /app
COPY build/libs/app.jar app.jar

# GC 멈춤을 시각과 함께 남긴다. 2단계 증거 수집기가 이 파일을 읽어 조회가 멈춘 때와 맞춰 본다
ENTRYPOINT ["java", "-Xlog:gc:file=/tmp/gc.log:time,uptime", "-jar", "/app/app.jar"]
