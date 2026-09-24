.PHONY: help install dev test lint format clean docker-build docker-up docker-down

help:
	@echo "Kullanılabilir komutlar:"
	@echo "  make install       - Bağımlılıkları yükle"
	@echo "  make dev           - Geliştirme sunucusunu başlat"
	@echo "  make test          - Testleri çalıştır"
	@echo "  make lint          - Kodu analiz et"
	@echo "  make format        - Kodu biçimlendir"
	@echo "  make clean         - Geçici dosyaları sil"
	@echo "  make docker-build  - Docker image'ı oluştur"
	@echo "  make docker-up     - Docker konteynerlerini başlat"
	@echo "  make docker-down   - Docker konteynerlerini durdur"
	@echo "  make api-docs      - FastAPI OpenAPI dokümantasyonunu aç"

install:
	pip install -r requirements-dev.txt

dev:
	uvicorn src.fastapi_app:app --reload --host 127.0.0.1 --port 8000

test:
	pytest tests/ -v --cov=src --cov-report=html

lint:
	black --check src/ tests/
	pylint src/
	mypy src/

format:
	black src/ tests/
	isort src/ tests/

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .coverage htmlcov .mypy_cache

docker-build:
	docker build -t wildfire-monitoring-system:latest .

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f app

api-docs:
	@echo "FastAPI docs: http://localhost:8000/docs"
