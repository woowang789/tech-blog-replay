# jcmd로 스레드 덤프를 뜰 수 있게 JRE가 아니라 JDK 이미지를 쓴다. java가 PID 1이라 `jcmd 1 Thread.print`로 뜬다
FROM eclipse-temurin:21-jdk

WORKDIR /app
COPY build/libs/app.jar app.jar

ENTRYPOINT ["java", "-jar", "/app/app.jar"]
