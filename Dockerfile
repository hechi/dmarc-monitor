FROM python:3.13-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

COPY pyproject.toml dmarc_monitor.py ./

RUN pip install --no-cache-dir . && \
    groupadd --system appgroup && \
    useradd --system --gid appgroup --no-create-home appuser

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/')" || exit 1

ENTRYPOINT ["dmarc-monitor"]
