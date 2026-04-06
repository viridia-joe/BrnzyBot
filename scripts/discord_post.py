"""
Post a message directly to Discord, bypassing the LLM.
Uses Node.js for the HTTP call (Python urllib gets 403 due to TLS differences).

Usage:
  from discord_post import post_to_discord
  post_to_discord(text)
"""

import json
import os
import subprocess

DEFAULT_CHANNEL = "379377073304633351"
BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
MAX_LENGTH = 2000


def post_to_discord(text, channel_id=None):
    """Post text directly to Discord channel. Returns True on success."""
    channel = channel_id or os.environ.get("DISCORD_CHANNEL_ID", DEFAULT_CHANNEL)

    # Split into chunks if over Discord's 2000 char limit
    chunks = []
    while text:
        if len(text) <= MAX_LENGTH:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, MAX_LENGTH)
        if split_at < MAX_LENGTH // 2:
            split_at = MAX_LENGTH
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    for chunk in chunks:
        # Use Node.js for the HTTP call
        js = f"""
const https = require('https');
const data = JSON.stringify({{content: {json.dumps(chunk)}}});
const req = https.request({{
  hostname: 'discord.com',
  path: '/api/v10/channels/{channel}/messages',
  method: 'POST',
  headers: {{
    'Authorization': 'Bot {BOT_TOKEN}',
    'Content-Type': 'application/json',
    'Content-Length': Buffer.byteLength(data)
  }}
}}, res => {{
  let body = '';
  res.on('data', c => body += c);
  res.on('end', () => process.exit(res.statusCode === 200 ? 0 : 1));
}});
req.on('error', () => process.exit(1));
req.write(data);
req.end();
"""
        try:
            result = subprocess.run(
                ["node", "-e", js],
                capture_output=True, timeout=10
            )
            if result.returncode != 0:
                print(f"Discord post failed (status {result.returncode})")
                return False
        except Exception as e:
            print(f"Discord post error: {e}")
            return False

    return True
