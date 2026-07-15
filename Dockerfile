# Стадия 1: сборка лендинга (Vite) в статику
FROM node:24-alpine AS landing-build
WORKDIR /landing
COPY landing/package*.json ./
RUN npm install --no-audit --no-fund
COPY landing/ .
RUN npm run build

# Стадия 2: Python-рантайм — бот + админка + собранный лендинг, один процесс
FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY --from=landing-build /landing/dist ./app/static_landing

ENV PORT=8080
ENV PYTHONPATH=/app

EXPOSE 8080

CMD ["sh", "-c", "uvicorn app.webhook:app --host 0.0.0.0 --port ${PORT:-8080}"]
