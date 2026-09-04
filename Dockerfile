FROM node:20-bookworm-slim AS frontend-build

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . ./
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

CMD ["sh", "-c", "uvicorn ui_server:app --host 0.0.0.0 --port ${PORT:-8000}"]
