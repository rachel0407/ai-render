FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    U2NET_HOME=/app/.u2net

# onnxruntime / Pillow runtime deps (libgomp for openmp, libgl/glib for Pillow fallbacks)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the birefnet-general model into the image so cold-start doesn't pull ~880MB
# on first request. U2NET_HOME is rembg's universal cache dir (name is historical/misleading —
# it holds whichever model you load).
# Retry up to 5 times — birefnet-general is ~880MB from HuggingFace and ChunkedEncodingError
# from a broken pipe is common on flaky networks during long downloads.
RUN set -e; \
    for i in 1 2 3 4 5; do \
        echo "[bake-model] attempt $i/5"; \
        python -c "from rembg import new_session; new_session('birefnet-general')" && exit 0; \
        echo "[bake-model] attempt $i failed, retrying in 10s..."; \
        sleep 10; \
    done; \
    echo "[bake-model] all attempts failed"; exit 1

COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
