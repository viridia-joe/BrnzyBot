---
name: wow-commands
description: "Intercept /strat, /gearcheck, /gearprio commands and run scripts directly — bypasses model"
metadata:
  {
    "openclaw": {
      "emoji": "⚔️",
      "events": ["message:received", "inbound_claim", "before_dispatch"],
      "requires": { "bins": ["python3", "bash"] }
    }
  }
---

# WoW Commands Hook

Intercepts TBC WoW commands and runs scripts directly. No LLM involved.

Commands: !strat, !gearcheck, !gearprio (also /strat, /gearcheck, /gearprio)
