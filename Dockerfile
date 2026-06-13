# ---- build stage: install Python deps ----
FROM python:3.12-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---- runtime stage ----
FROM python:3.12-slim

# ffmpeg for audio extraction and quality merging
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# non-root user for security
RUN useradd -m -u 1000 appuser

# copy installed Python packages from builder
COPY --from=builder /install /usr/local

WORKDIR /app
COPY app/ ./app/

# temp download dir — owned by appuser
RUN mkdir -p /tmp/svd-downloads && chown appuser:appuser /tmp/svd-downloads

USER appuser

EXPOSE 8000

# 2 workers: enough for a €5 VPS (1 vCPU), change to 4 on bigger boxes
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "2", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*"]
