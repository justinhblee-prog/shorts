FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg clamav clamav-freshclam util-linux fonts-noto-cjk fontconfig \
    && rm -rf /var/lib/apt/lists/*
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN ffmpeg -hide_banner -filters 2>&1 | grep -q drawtext \
    && test -f /usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./backend/
COPY frontend/ ./frontend/
RUN mkdir -p /app/data /app/data/media
WORKDIR /app/backend
EXPOSE 8502
CMD ["uvicorn","app:app","--host","0.0.0.0","--port","8502"]
