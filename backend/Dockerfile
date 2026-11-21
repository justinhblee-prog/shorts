FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg=7:7.1.5-0+deb13u1 clamav clamav-freshclam fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
COPY backend/media-binaries.sha256 /usr/share/nexus-media-binaries.sha256
RUN sha256sum --check /usr/share/nexus-media-binaries.sha256
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./backend/
COPY frontend/ ./frontend/
RUN mkdir -p /app/data /app/data/media
WORKDIR /app/backend
EXPOSE 8502
CMD ["uvicorn","app:app","--host","0.0.0.0","--port","8502"]
