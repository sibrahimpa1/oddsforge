FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app/backend
COPY backend/pyproject.toml ./
COPY backend/oddsforge ./oddsforge
RUN pip install --no-cache-dir -e .
COPY data/raw /app/data/raw
COPY data/reports /app/data/reports
ENV ODDSFORGE_DATA_DIR=/app/data
EXPOSE 8000
# First start builds the database and the walk-forward predictions from the bundled raw data (~3 min).
CMD ["sh", "-c", "[ -f /app/data/oddsforge.db ] || oddsforge all; uvicorn oddsforge.api:app --host 0.0.0.0 --port 8000"]
