"""
OpenClaw Raid Analyst — Node health check.

Polls each Ollama node via /api/ps before the analyst runs.
A node is considered available if it responds quickly and has
no model actively generating (size_vram == 0 or empty models list).

If a node is unavailable, posts a private status message to Discord
using a lookup table. The message text is deliberately indirect —
a nod between the bot and its operator. No one else needs to know
what "I've misplaced my Icepick" means.

Entry point: check_nodes() -> NodeStatus
"""

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import config

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Node definitions
# ---------------------------------------------------------------------------
NODES = {
    "tomahawk": {
        "ip":       "10.0.0.223",
        "gpu":      "RTX 4090",
        "vram_gb":  24,
        "models":   ["deepseek-r1:32b", "qwen2.5:14b", "llama3.1:8b"],
    },
    "cudgel": {
        "ip":       "10.0.0.219",
        "gpu":      "RTX 3090",
        "vram_gb":  24,
        "models":   ["deepseek-r1:32b", "qwen2.5:14b", "llama3.1:8b"],
    },
    "icepick": {
        "ip":       "10.0.0.97",
        "gpu":      "RTX 5080",
        "vram_gb":  16,
        "models":   ["qwen2.5:14b", "llama3.1:8b", "mistral"],
    },
    "jarvis": {
        "ip":       "127.0.0.1",
        "gpu":      "RTX 2080 Super",
        "vram_gb":  8,
        "models":   ["llama3.1:8b"],
        "degraded": True,   # Always treat as last resort regardless of status
    },
}

# Maximum response time before we consider a node busy (ms)
_BUSY_THRESHOLD_MS = 600

# ---------------------------------------------------------------------------
# Private status message lookup table.
# Only the bot and its operator know what these mean.
# "busy" = sharpening / embedded / occupied
# "down" = misplaced / confiscated / lost
# ---------------------------------------------------------------------------
_STATUS_MESSAGES = {
    "tomahawk": {
        "busy": "My Tomahawk is embedded in something. Proceeding without it.",
        "down": "My Tomahawk appears to have been confiscated.",
    },
    "cudgel": {
        "busy": "My Cudgel is being sharpened. I'll manage.",
        "down": "I seem to have misplaced my Cudgel.",
    },
    "icepick": {
        "busy": "My Icepick is currently chipping away at something else.",
        "down": "I've lost my Icepick entirely.",
    },
    "jarvis": {
        "busy": "Even my reserves are occupied. This may take a moment.",
        "down": "Running on fumes. Answers may be brief.",
    },
}

_ALL_DOWN_MESSAGE = (
    "All my weapons appear to be missing. Falling back to Claude — "
    "this one's on the house."
)

_DEGRADED_LOCAL_MESSAGE = (
    "The fleet is otherwise engaged. Running on emergency reserves — "
    "answers will be terse."
)


# ---------------------------------------------------------------------------
# Data structure
# ---------------------------------------------------------------------------
@dataclass
class NodeStatus:
    """Result of a full fleet health check."""
    available:  dict = field(default_factory=dict)  # name → node_info dict
    busy:       dict = field(default_factory=dict)
    down:       dict = field(default_factory=dict)
    jarvis_ok:  bool = False
    fleet_idle: bool = False   # True if at least one non-jarvis node is available

    def can_run_32b(self) -> bool:
        """True if Tomahawk or Cudgel is available (32B capable nodes)."""
        return "tomahawk" in self.available or "cudgel" in self.available

    def can_run_14b(self) -> bool:
        """True if any fleet node is available (all have at least 14B models)."""
        return bool(self.available - {"jarvis"} if isinstance(self.available, set)
                    else {k: v for k, v in self.available.items() if k != "jarvis"})

    def best_for_8b(self) -> list[str]:
        """Return available nodes in capability order for 8B tasks."""
        order = ["icepick", "tomahawk", "cudgel"]
        result = [n for n in order if n in self.available]
        if self.jarvis_ok:
            result.append("jarvis")
        return result


# ---------------------------------------------------------------------------
# Poll a single node
# ---------------------------------------------------------------------------
def _poll_node(name: str, info: dict) -> str:
    """
    Returns 'idle', 'busy', or 'down'.
    'idle'  — responded quickly, no active generation
    'busy'  — responding slowly (>threshold) OR has a model actively loaded
    'down'  — unreachable or error
    """
    url = f"http://{info['ip']}:11434/api/ps"
    t0 = time.monotonic()

    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            elapsed_ms = (time.monotonic() - t0) * 1000
            data = json.loads(resp.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return "down"

    # Slow response — something is loading or the machine is under load
    if elapsed_ms > _BUSY_THRESHOLD_MS:
        log.debug("  %s: slow response %.0fms — marking busy", name, elapsed_ms)
        return "busy"

    # Check if any model is actively using VRAM (i.e. currently generating)
    active = [
        m for m in data.get("models", [])
        if m.get("size_vram", 0) > 0
    ]
    if active:
        model_names = [m["name"] for m in active]
        log.debug("  %s: active models %s — marking busy", name, model_names)
        return "busy"

    return "idle"


# ---------------------------------------------------------------------------
# Full fleet check
# ---------------------------------------------------------------------------
def check_nodes(post_alerts: bool = True) -> NodeStatus:
    """
    Poll all nodes and return a NodeStatus.
    If post_alerts=True, posts Discord messages for any unavailable nodes.
    """
    status = NodeStatus()
    alerts = []

    log.info("Node health check:")
    for name, info in NODES.items():
        result = _poll_node(name, info)
        log.info("  %-10s %s", name, result)

        if result == "idle":
            status.available[name] = info
            if name == "jarvis":
                status.jarvis_ok = True
        elif result == "busy":
            status.busy[name] = info
            if name != "jarvis":  # jarvis busy is not worth alerting
                msg = _STATUS_MESSAGES[name]["busy"]
                alerts.append(msg)
                log.warning("  %s busy: %s", name, msg)
        else:  # down
            status.down[name] = info
            msg = _STATUS_MESSAGES[name]["down"]
            alerts.append(msg)
            log.warning("  %s down: %s", name, msg)

    # Determine fleet state
    fleet_nodes = {k: v for k, v in status.available.items() if k != "jarvis"}
    status.fleet_idle = bool(fleet_nodes)

    # Special case: all fleet nodes unavailable
    if not status.fleet_idle:
        if status.jarvis_ok:
            alerts = [_DEGRADED_LOCAL_MESSAGE]  # Replace individual alerts
        else:
            alerts = [_ALL_DOWN_MESSAGE]

    if post_alerts and alerts:
        _post_alerts(alerts)

    return status


# ---------------------------------------------------------------------------
# Discord alert posting
# ---------------------------------------------------------------------------
def _post_alerts(messages: list[str]) -> None:
    """Post node status alerts to the raid recap channel."""
    try:
        import discord_post
        combined = "\n".join(f"_{m}_" for m in messages)
        discord_post.post(combined)
    except Exception as e:
        log.error("Failed to post node health alerts to Discord: %s", e)
