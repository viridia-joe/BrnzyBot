# TOOLS.md - WoW TBC Gear System

All gear data is local. No external fetches needed for routine queries.

**Local item database:** `~/.openclaw/data/tbc_items.db` — 4500+ TBC items with stats, sources, phase tags. Sourced from WowSims.

**Stat weights:** `~/.openclaw/data/weights/<spec>.json` — per-spec EP weights. Run `ls ~/.openclaw/data/weights/` to see available specs.

**Gear refresh script:** `~/.openclaw/scripts/compute-upgrades.py`
- Fetches current gear from WCL (only external call, 3 API requests)
- Computes EP from local database + weight files
- Writes GEAR-STATUS.md
- Usage: `python3 ~/.openclaw/scripts/compute-upgrades.py --name NAME --server SERVER --spec SPEC`

**Phase check script:** `~/.openclaw/scripts/check-phase.sh`
- Detects current TBC phase from WCL raid zone activity
- Updates PHASE.md
- Run daily via heartbeat

**Wowhead (backup only):**
- Tooltip API: `https://nether.wowhead.com/tbc/tooltip/item/{ITEM_ID}`
- Search: `site:wowhead.com/tbc {item name}`
