FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends stockfish && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /data

EXPOSE 8080

CMD gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 2 --timeout 120 app:app
