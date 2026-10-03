# Shared multi-stage build for all Java services.
# Usage (compose passes this): --build-arg SERVICE=order-service
FROM maven:3.9-eclipse-temurin-21 AS build
ARG SERVICE
WORKDIR /build
COPY ${SERVICE}/pom.xml .
RUN mvn -q -B dependency:go-offline
COPY ${SERVICE}/src ./src
RUN mvn -q -B package -DskipTests

FROM eclipse-temurin:21-jre
WORKDIR /app
# OpenTelemetry Java agent: auto-instruments HTTP, JDBC, and logging with zero code changes
ADD https://github.com/open-telemetry/opentelemetry-java-instrumentation/releases/latest/download/opentelemetry-javaagent.jar /otel/opentelemetry-javaagent.jar
COPY --from=build /build/target/*.jar app.jar
ENTRYPOINT ["java", "-javaagent:/otel/opentelemetry-javaagent.jar", "-jar", "/app/app.jar"]
