# ReelFlow server: web app + scheduler + Reel engine. Build from the REPO ROOT:
#   docker build -f reelflow/Dockerfile -t reelflow .
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg git && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir kokoro-onnx soundfile numpy pillow fastapi uvicorn python-multipart jinja2
WORKDIR /app
COPY engine ./engine
COPY reelflow ./reelflow
ENV REELFLOW_DATA=/data/clients PYTHONUNBUFFERED=1
WORKDIR /app/reelflow
EXPOSE 8000
CMD ["python3", "-m", "reelflow", "serve"]
