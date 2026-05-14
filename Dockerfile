FROM python:3.12-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ── runtime image ────────────────────────────────────────────────────────────
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        procps lsof net-tools \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

WORKDIR /app
COPY collector.py app.py entrypoint.sh ./
RUN chmod +x entrypoint.sh

VOLUME ["/data"]
EXPOSE 8080

ENTRYPOINT ["/app/entrypoint.sh"]
