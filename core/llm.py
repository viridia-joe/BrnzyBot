"""
Single LiteLLM (OpenAI-compatible) client.

Every LLM call in the bot goes through `chat()`, so the endpoint, auth header,
timeout, and error shape live in exactly one place (previously copy-pasted into
five modules). Transport only — callers keep their own `config.ENABLE_LLM`
guards and decide how to handle failure.

The bot talks to the LiteLLM proxy over plain HTTP — no SDK dependency (keeps the
1 GB box light). `messages` is passed straight through, so vision/image-content
payloads work unchanged.
"""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import config

DEFAULT_TIMEOUT = 60


def chat(model: str, messages: list, *, temperature: float = 0.3,
         max_tokens: int = 1024, timeout: int = DEFAULT_TIMEOUT) -> str:
    """
    POST to `{LITELLM_BASE_URL}/chat/completions` and return the assistant's
    content string. Raises RuntimeError on any transport/parse failure so callers
    can fall back deterministically.
    """
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {"Content-Type": "application/json"}
    if config.LITELLM_API_KEY:
        headers["Authorization"] = f"Bearer {config.LITELLM_API_KEY}"

    req = Request(f"{config.LITELLM_BASE_URL}/chat/completions",
                  data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"]
    except (HTTPError, URLError, OSError, KeyError, ValueError, TimeoutError) as e:
        raise RuntimeError(f"LLM call failed: {e}") from e
