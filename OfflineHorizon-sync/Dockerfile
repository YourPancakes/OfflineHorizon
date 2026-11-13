FROM python:3.12-alpine
RUN apk add --no-cache git ca-certificates openssh-client \
    && mkdir -p /work \
    && chown 10001:10001 /work
WORKDIR /app
COPY sync.py scheduler.py calendar_schedule.py manifest.txt release_fallback.py /app/
ENV PYTHONUNBUFFERED=1 \
    GIT_TERMINAL_PROMPT=0 \
    PYTHONDONTWRITEBYTECODE=1
USER 10001:10001
ENTRYPOINT ["python", "/app/scheduler.py"]
