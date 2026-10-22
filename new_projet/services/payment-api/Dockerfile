# Contexte de build : services/ (pour inclure le paquet common/)
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app
WORKDIR /app
COPY payment-api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY common ./common
COPY payment-api/app ./app
RUN useradd --system --no-create-home --uid 10001 app
USER 10001
# 8000 : API (relayée par le proxy) ; 9000 : métriques (réseau interne uniquement)
EXPOSE 8000 9000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*' --no-access-log --root-path \"${ROOT_PATH:-}\""]
