#!/usr/bin/env python3
"""
Log user feedback from Discord reactions.
Called with: python3 log-feedback.py <positive|negative> <user> <message_snippet>

Stores feedback in ~/.openclaw/data/feedback.jsonl
"""

import json
import os
import sys
from datetime import datetime, timezone

FEEDBACK_PATH = os.path.expanduser("~/.openclaw/data/feedback.jsonl")


def main():
    if len(sys.argv) < 3:
        print("Usage: log-feedback.py <positive|negative> <user> [message_snippet]")
        return

    sentiment = sys.argv[1]  # "positive" or "negative"
    user = sys.argv[2]
    snippet = " ".join(sys.argv[3:]) if len(sys.argv) > 3 else ""

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sentiment": sentiment,
        "user": user,
        "snippet": snippet[:200],
    }

    with open(FEEDBACK_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")

    if sentiment == "negative":
        print(f"Thanks for the feedback. What was wrong? Reply with details and I'll log it for improvement.")
    else:
        print(f"Glad that helped!")


if __name__ == "__main__":
    main()
