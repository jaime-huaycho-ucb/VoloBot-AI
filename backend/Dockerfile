FROM python:3.11-slim

# ffmpeg: requerido por faster-whisper para decodificar/convertir audio
# fonts-dejavu-core: fuente con acentos/¿¡ para las pantallas que dibuja images.py
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000

ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
