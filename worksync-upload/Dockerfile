# One image, one address: the backend serves the built website and the API.
# Build:  docker build -t worksync .      Run:  docker run -p 8000:8000 worksync   ->  http://localhost:8000
FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# An empty API base means "the same address the page came from".
ENV VITE_API_BASE_URL=""
RUN npm run build

# Python 3.9 is the version the 130 backend tests were run on.
FROM python:3.9-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    WORKSYNC_STATIC_DIR=/app/static \
    WORKSYNC_DB=/data/worksync.db \
    WORKSYNC_BEHIND_PROXY=1
WORKDIR /app
COPY backend/requirements-deploy.txt ./
RUN pip install --no-cache-dir -r requirements-deploy.txt
COPY backend/ ./
RUN rm -rf tests worksync.db* .venv __pycache__ && mkdir -p /data
COPY --from=web /web/dist /app/static
EXPOSE 8000
# $PORT is set by hosts such as Render; 8000 otherwise.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
