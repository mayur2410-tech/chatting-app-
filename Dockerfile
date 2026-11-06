# Duo: one container serving the website and the API (same origin, so the secure session cookie
# and the chat WebSocket work without cross-site settings).

# --- 1. Build the website --------------------------------------------------------------------
FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- 2. API + built site ---------------------------------------------------------------------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ENVIRONMENT=production \
    COOKIE_SECURE=true \
    STATIC_DIR=/app/static

WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt

COPY backend/ ./
COPY --from=web /web/dist ./static

# Run as an unprivileged user.
RUN useradd --create-home --uid 10001 duo && chown -R duo /app
USER duo

# Render provides $PORT. Migrations run on every start (no-op when up to date).
# --proxy-headers: Render terminates HTTPS in front of the app; trust its forwarded headers.
# Single worker on purpose: live connections and rate limits are kept in process memory.
EXPOSE 10000
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000} --proxy-headers --forwarded-allow-ips='*' --ws-max-size 65536"]
