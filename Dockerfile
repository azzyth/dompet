FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY dompet ./dompet
COPY configs ./configs
COPY db ./db
COPY scripts ./scripts
COPY tests ./tests

# Keep the fixture-free demo path working from inside the container:
#   docker compose exec api python scripts/seed_demo.py
#   docker compose exec api python -m dompet.ml.train --config configs/train.yaml
#   docker compose exec api python -m unittest discover -s tests   (DB tests run here)
RUN mkdir -p models

EXPOSE 8000

# /health is the container healthcheck target (see docker-compose.yml).
CMD ["uvicorn", "dompet.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
