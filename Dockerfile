# Multi-stage: build the React bundle with node, serve it (and the API) from python.
#
# The frontend is a build artefact, not source — `frontend/dist/` is gitignored, so the
# image builds it here rather than trusting whatever happened to be on a developer's disk.

# ---------------------------------------------------------------- stage 1: UI
FROM node:20-alpine AS ui

WORKDIR /ui
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ------------------------------------------------------------ stage 2: runtime
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY scripts/ scripts/
# Sample inputs only. data/ectsum/ is a large unused dataset — copying data/ wholesale
# would balloon the image for nothing.
COPY data/samples/ data/samples/
COPY --from=ui /ui/dist /app/frontend/dist

ENV PYTHONUNBUFFERED=1 \
    STORAGE_DIR=/app/storage_data \
    OUTPUT_DIR=/app/output \
    FRONTEND_DIST=/app/frontend/dist

RUN mkdir -p /app/storage_data /app/output

EXPOSE 8000

# Optional local OCR (§5.6 tier 2). Off by default: it reads text but understands
# nothing — a risk heatmap is colour and position, and OCR sees neither. To enable:
#   RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr \
#       && rm -rf /var/lib/apt/lists/*
#   RUN pip install --no-cache-dir -r requirements-ocr.txt

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
