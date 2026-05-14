#!/bin/sh
# entrypoint — starts collector in background, then web server in foreground.
set -e

echo "[entrypoint] sysstat-recorder starting..."

# Run collector in background
python3 /app/collector.py &
COLLECTOR_PID=$!
echo "[entrypoint] collector PID=$COLLECTOR_PID"

# Trap to stop collector when container stops
trap "kill $COLLECTOR_PID 2>/dev/null; exit 0" SIGTERM SIGINT

# Start web server (gunicorn for production, fallback to flask dev server)
if command -v gunicorn >/dev/null 2>&1; then
    echo "[entrypoint] starting gunicorn on 0.0.0.0:${SYSSTAT_PORT:-8080}"
    exec gunicorn --bind 0.0.0.0:${SYSSTAT_PORT:-8080} \
        --workers 2 \
        --threads 4 \
        --timeout 30 \
        --access-logfile - \
        --error-logfile - \
        app:app
else
    echo "[entrypoint] starting flask dev server"
    exec python3 /app/app.py
fi
