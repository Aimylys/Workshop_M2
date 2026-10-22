FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY config.yaml .
# Utilisateur non-root ; /blocklist est la seule zone d'écriture (volume partagé avec le WAF)
RUN useradd -r -u 10001 orchestrator && mkdir /blocklist && chown 10001 /blocklist
USER 10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
