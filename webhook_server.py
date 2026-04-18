"""
BrnzyBot Stripe Webhook Server.

Runs as a standalone process on Jarvis alongside the Discord bot.
Receives Stripe webhook events and updates the subscriptions table.

Exposes:
    GET  /health           — liveness check (used by UptimeRobot / Cloudflare)
    POST /stripe/webhook   — Stripe event receiver

Usage:
    python webhook_server.py

Requires in ~/.openclaw/data/.env:
    STRIPE_WEBHOOK_SECRET=whsec_...
    STRIPE_PAYMENT_LINK=https://buy.stripe.com/...

Cloudflare Tunnel forwards <your-subdomain>/stripe/webhook to localhost:8080.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

# Load .env the same way config.py does
_ENV_PATH = os.path.expanduser("~/.openclaw/data/.env")
if os.path.exists(_ENV_PATH):
    with open(_ENV_PATH) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

sys.path.insert(0, os.path.dirname(__file__))

from db.server_config import upsert_subscription

WEBHOOK_SECRET: str = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
PORT: int           = int(os.environ.get("WEBHOOK_PORT", "8080"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s [webhook] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            os.path.expanduser("~/.openclaw/logs/brnzybot_webhook.log"),
            encoding="utf-8",
        ),
    ],
)
log = logging.getLogger("webhook")


# ---------------------------------------------------------------------------
# Stripe signature verification
# ---------------------------------------------------------------------------

def _verify_signature(payload: bytes, sig_header: str, secret: str) -> bool:
    """Verify Stripe webhook signature (v1 scheme)."""
    if not secret:
        log.warning("STRIPE_WEBHOOK_SECRET not set — skipping signature verification")
        return True
    try:
        parts  = {k: v for k, v in (p.split("=", 1) for p in sig_header.split(","))}
        ts     = parts.get("t", "")
        v1_sig = parts.get("v1", "")
        signed = f"{ts}.{payload.decode()}"
        expected = hmac.new(secret.encode(), signed.encode(), hashlib.sha256).hexdigest()
        # Reject if timestamp is > 5 minutes old
        if abs(time.time() - int(ts)) > 300:
            log.warning("Stripe webhook timestamp too old: %s", ts)
            return False
        return hmac.compare_digest(expected, v1_sig)
    except Exception as e:
        log.warning("Signature verification error: %s", e)
        return False


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------

def _handle_event(event: dict) -> None:
    event_type = event.get("type", "")
    obj        = event.get("data", {}).get("object", {})

    log.info("Stripe event: %s", event_type)

    if event_type in ("customer.subscription.created", "customer.subscription.updated"):
        customer_id = obj.get("customer")
        sub_id      = obj.get("id")
        status      = obj.get("status", "active")  # active, past_due, canceled, trialing
        # metadata.guild_id must be set in Stripe checkout session
        guild_id    = obj.get("metadata", {}).get("guild_id")
        plan        = "pro" if status in ("active", "trialing") else "free"

        if not guild_id:
            log.warning("No guild_id in subscription metadata for sub %s", sub_id)
            return

        upsert_subscription(
            guild_id=guild_id,
            plan=plan,
            status=status,
            stripe_customer_id=customer_id,
            stripe_sub_id=sub_id,
        )
        log.info("Updated subscription for guild %s: plan=%s status=%s", guild_id, plan, status)

    elif event_type == "customer.subscription.deleted":
        customer_id = obj.get("customer")
        sub_id      = obj.get("id")
        guild_id    = obj.get("metadata", {}).get("guild_id")

        if not guild_id:
            log.warning("No guild_id in deleted subscription metadata for sub %s", sub_id)
            return

        upsert_subscription(
            guild_id=guild_id,
            plan="free",
            status="canceled",
            stripe_customer_id=customer_id,
            stripe_sub_id=sub_id,
        )
        log.info("Subscription canceled for guild %s", guild_id)

    elif event_type == "invoice.payment_failed":
        sub_id   = obj.get("subscription")
        # Find the guild by stripe_sub_id — requires a lookup we don't have yet.
        # For now just log it; a future improvement is to DM the guild owner.
        log.warning("Payment failed for subscription %s", sub_id)


# ---------------------------------------------------------------------------
# HTTP request handler
# ---------------------------------------------------------------------------

class WebhookHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # suppress default access log spam
        pass

    def do_GET(self):
        if self.path == "/health":
            self._respond(200, json.dumps({"status": "ok", "service": "brnzybot-webhook"}).encode())
        else:
            self._respond(404, b"Not found")

    def do_POST(self):
        if self.path != "/stripe/webhook":
            self._respond(404, b"Not found")
            return

        length  = int(self.headers.get("Content-Length", 0))
        payload = self.rfile.read(length)
        sig     = self.headers.get("Stripe-Signature", "")

        if not _verify_signature(payload, sig, WEBHOOK_SECRET):
            log.warning("Invalid Stripe signature — rejecting")
            self._respond(400, b"Invalid signature")
            return

        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            self._respond(400, b"Bad JSON")
            return

        try:
            _handle_event(event)
        except Exception as e:
            log.exception("Error handling Stripe event: %s", e)
            self._respond(500, b"Internal error")
            return

        self._respond(200, b"OK")

    def _respond(self, code: int, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json" if body.startswith(b"{") else "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run():
    os.makedirs(os.path.expanduser("~/.openclaw/logs"), exist_ok=True)
    server = HTTPServer(("0.0.0.0", PORT), WebhookHandler)
    log.info("Webhook server listening on port %d", PORT)
    log.info("Health:  GET  /health")
    log.info("Stripe:  POST /stripe/webhook")
    server.serve_forever()


if __name__ == "__main__":
    run()
