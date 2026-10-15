# Build from repo root:  docker build -f server/Dockerfile -t mcbench-api .
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data STATIC_DATA=/app/web/data
WORKDIR /app
COPY pyproject.toml README.md ./
COPY mcbench ./mcbench
COPY web/data ./web/data
COPY server ./server
RUN pip install --no-cache-dir -e . -r server/requirements.txt && useradd -r -u 10001 app && mkdir -p /data && chown app /data
USER app
WORKDIR /app/server
EXPOSE 8787
HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8787/api/health')"
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8787", "--proxy-headers", "--no-server-header"]
