FROM python:3.11-slim

WORKDIR /app

# numpy / scipy / Pillow / discord.py all ship manylinux wheels for cp311, so
# nothing is compiled from source — no build toolchain needed. This keeps the
# image small and the build fast enough to finish on a free-tier e2-micro.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Runtime data lives outside the image; mount /root/.openclaw at container start
RUN mkdir -p /root/.openclaw/data /root/.openclaw/logs

# Default: run the Discord bot.
# Override with `command: python webhook_server.py` for the webhook service.
CMD ["python", "bot.py"]
