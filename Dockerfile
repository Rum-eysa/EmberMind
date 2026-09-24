FROM python:3.11-slim

WORKDIR /app

# Sistem bağımlılıkları
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    gdal-bin \
    libgdal-dev \
    && rm -rf /var/lib/apt/lists/*

# Python bağımlılıkları
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Uygulama kodunu kopyala
COPY . .

# Port
EXPOSE 8000

# Sağlık kontrolü
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import requests; response = requests.get('http://localhost:8000/health', timeout=5); response.raise_for_status()"

# Çalıştır
CMD ["uvicorn", "src.fastapi_app:app", "--host", "0.0.0.0", "--port", "8000"]
