FROM python:3.11-slim

WORKDIR /app

# scipy/numpy need these at build time on slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Runtime data lives outside the image; mount /root/.openclaw at container start
RUN mkdir -p /root/.openclaw/data /root/.openclaw/logs

# Default: run the Discord bot.
# Override with `command: python webhook_server.py` for the webhook service.
CMD ["python", "bot.py"]
