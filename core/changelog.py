"""
Deploy changelog — on a fresh deploy, summarize what changed since the last
announced commit into New Features / Improvements / Bug Fixes, one line each.

The heartbeat posts this once per deploy (instead of the usual lore post) when it
detects the running git SHA differs from the last-announced SHA. Deterministic:
the summary is built from conventional-commit subjects (feat/fix/perf/refactor…),
no LLM.
"""

from __future__ import annotations

import logging
import os
import subprocess

log = logging.getLogger(__name__)

try:
    import config
    _STATE_PATH = os.path.join(os.path.dirname(config.BOT_DB_PATH), "last_announced_sha")
except Exception:  # pragma: no cover
    _STATE_PATH = os.path.expanduser("~/.openclaw/data/last_announced_sha")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The deploy step bakes these in (the slim container has no git binary).
_SHA_FILE = os.path.join(_REPO, ".deploy_sha")
_LOG_FILE = os.path.join(_REPO, ".deploy_log")


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def _git(*args: str) -> str:
    """Fallback to the git binary for local dev (the container uses _read)."""
    try:
        return subprocess.check_output(
            ["git", *args], cwd=_REPO, stderr=subprocess.DEVNULL, text=True
        ).strip()
    except Exception:
        return ""


def current_sha() -> str:
    return _read(_SHA_FILE) or _git("rev-parse", "HEAD")


def _last_announced() -> str:
    try:
        with open(_STATE_PATH, encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def _save_announced(sha: str) -> None:
    try:
        os.makedirs(os.path.dirname(_STATE_PATH), exist_ok=True)
        with open(_STATE_PATH, "w", encoding="utf-8") as f:
            f.write(sha)
    except Exception as e:
        log.warning("could not save announced sha: %s", e)


# Conventional-commit type → changelog bucket.
_FEATURE = ("feat",)
_FIX = ("fix", "bug")
_IMPROVE = ("perf", "refactor", "improve", "harden", "feat(improve)")

# Subjects we never surface to users (internal/noise).
_SKIP_SCOPES = ("docs", "test", "chore", "ci", "build", "style", "backlog")


def _clean_subject(subject: str) -> str:
    """Drop the 'type(scope): ' prefix and capitalize for a user-facing line."""
    body = subject.split(":", 1)[1].strip() if ":" in subject else subject
    return body[:1].upper() + body[1:] if body else subject


def _bucket(subject: str) -> str | None:
    head = subject.split(":", 1)[0].lower()
    type_ = head.split("(", 1)[0]
    scope = head[head.find("(") + 1:head.find(")")] if "(" in head else ""
    if type_ in _SKIP_SCOPES or scope in _SKIP_SCOPES:
        # a docs/test/chore commit — skip unless it's a feat/fix anyway
        if type_ not in (*_FEATURE, *_FIX):
            return None
    if type_ in _FEATURE:
        return "features"
    if type_ in _FIX:
        return "fixes"
    if type_ in _IMPROVE:
        return "improvements"
    return None


def _subjects_since(since_sha: str) -> list[str]:
    """Commit subjects from HEAD back to (but not including) since_sha.
    Reads the deploy-baked '.deploy_log' (sha + subject lines); falls back to git."""
    raw = _read(_LOG_FILE)
    if raw:
        subjects = []
        for line in raw.splitlines():
            sha, _, subject = line.partition(" ")
            if since_sha and sha.startswith(since_sha[:12]):
                break  # reached the last-announced commit
            subjects.append(subject)
        return subjects
    # local dev fallback
    rng = f"{since_sha}..HEAD" if since_sha else "-20"
    out = _git("log", rng, "--pretty=%s") if since_sha else _git("log", "-20", "--pretty=%s")
    return out.splitlines() if out else []


def build_changelog(since_sha: str, max_per_bucket: int = 6) -> str | None:
    """Render the changelog between since_sha..HEAD, or None if nothing notable."""
    subjects = _subjects_since(since_sha)
    if not subjects:
        return None

    buckets: dict[str, list[str]] = {"features": [], "improvements": [], "fixes": []}
    seen: set[str] = set()
    for subject in subjects:
        if subject.startswith("Merge "):
            continue
        b = _bucket(subject)
        if not b:
            continue
        line = _clean_subject(subject)
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        if len(buckets[b]) < max_per_bucket:
            buckets[b].append(line)

    if not any(buckets.values()):
        return None

    parts = ["🚀 **BrnzyBot updated!** Here's what's new:"]
    titles = [("features", "✨ New Features"),
              ("improvements", "🔧 Improvements"),
              ("fixes", "🐛 Bug Fixes")]
    for key, title in titles:
        if buckets[key]:
            parts.append(f"\n**{title}**")
            parts.extend(f"• {line}" for line in buckets[key])
    return "\n".join(parts)


def deploy_changelog_if_new() -> str | None:
    """
    If the running commit differs from the last announced one, return a changelog
    string and record this commit as announced. Returns None when nothing changed
    (so the heartbeat falls back to its normal lore post).
    """
    sha = current_sha()
    if not sha:
        return None
    last = _last_announced()
    if sha == last:
        return None
    msg = build_changelog(last)
    _save_announced(sha)   # record even if msg is None, so we don't retry endlessly
    return msg
