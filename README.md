# TBC Gear Advisor for OpenClaw

A local-first World of Warcraft TBC gear and strategy advisory system for [OpenClaw](https://github.com/openclaw/openclaw) bots. Computes EP-based upgrade recommendations from a local item database, with current gear pulled from Warcraft Logs. Includes boss strategy guides for all Phase 1 content.

**Zero API cost for routine queries.** All gear data and boss strategies are local. External calls (WCL API) only happen on gear refresh — max 3 requests, max 1x/day.

## What It Does

Three Discord commands, powered by local scripts — no LLM reasoning required:

```
!strat <boss or raid>        — Boss strategy: abilities, what kills people, prep
!gearcheck <character>       — Current gear with EP values from WCL
!gearprio <character> <raid> — Top 3 upgrades available from a specific raid
```

## Prerequisites

- **OpenClaw** installed and running with Discord channel configured
- **Python 3.8+** (stdlib only — no pip packages)
- **curl** and **bash**
- **Ollama** with **Qwen 2.5 7B** (recommended model for tool calling)
- **Warcraft Logs v2 API client** (free — [get one here](https://www.warcraftlogs.com/api/docs))

### Model Requirements

The bot needs a local model that reliably calls OpenClaw's `exec` tool:

| Model | Tool Calling | Recommended |
|-------|-------------|-------------|
| **Qwen 2.5 7B** | Works | **Yes** |
| Mistral 7B | Narrates tool calls as text | No |
| Llama 3.1 8B | Inconsistent tool invocation | No |

## Quick Start

```bash
git clone <repo-url> tbc-gear-advisor
cd tbc-gear-advisor
bash setup.sh
```

The setup script prompts for WCL API credentials, downloads WowSims item data, builds the SQLite database, enriches items with sources from Wowhead (~15 min), and applies boss loot tables and tier token mappings.

Then copy workspace templates:

```bash
cp workspace-templates/AGENTS.md ~/.openclaw/workspace/
cp workspace-templates/SOUL.md ~/.openclaw/workspace/
cp workspace-templates/TOOLS.md ~/.openclaw/workspace/
cp workspace-templates/TBC.md ~/.openclaw/workspace/
cp workspace-templates/USER.md ~/.openclaw/workspace/
```

Edit `USER.md` with your info. Restart the bot.

### Critical: Keep AGENTS.md Minimal

The working `AGENTS.md` is ~20 lines. This is intentional. 7B models cannot follow complex multi-page instructions. The command table must be the most prominent thing in the file. Don't bloat it.

### Critical: Session Reset After Config Changes

OpenClaw sessions persist model and tool config from session creation. After changing the model or AGENTS.md:

1. Archive session files: `mv ~/.openclaw/agents/main/sessions/*.jsonl ~/.openclaw/agents/main/sessions/archived/`
2. Reset metadata in `sessions.json`: clear `sessionFile`, set `systemSent: false`
3. Restart: `systemctl --user restart openclaw-gateway.service`

Just restarting is NOT enough.

## Architecture

```
!strat Prince → LLM calls exec → strat.py reads boss_strats.json → posts to Discord
!gearprio Thrall Kara → LLM calls exec → gearprio.py queries WCL + SQLite → posts ranked upgrades
!gearcheck Thrall → LLM calls exec → gearcheck.py queries WCL + SQLite → posts current gear
```

The LLM's only job is recognizing the `!command` pattern and calling `exec`. All data processing happens in Python with a local SQLite database.

## What's Included

- **4500+ item SQLite database** with full stats from WowSims
- **26 spec weight files** — every TBC PvE spec, all classes and roles
- **13 boss strategies** — all Phase 1 (Karazhan, Gruul's Lair, Magtheridon's Lair)
- **Source enrichment** — boss names, tier token mappings, crafted/rep/badge tagging
- **Class restriction filtering** — won't recommend wrong-class tier pieces
- **Phase awareness** — auto-detects current phase from WCL activity

## Repo Structure

```
tbc-gear-advisor/
├── scripts/
│   ├── strat.py                # !strat — boss strategy lookup
│   ├── gearcheck.py            # !gearcheck — current gear with EP
│   ├── gearprio.py             # !gearprio — top upgrades from a raid
│   ├── cmd-strat.sh            # Shell wrappers
│   ├── cmd-gearcheck.sh
│   ├── cmd-gearprio.sh
│   ├── compute-upgrades.py     # Full upgrade report → GEAR-STATUS.md
│   ├── check-phase.sh          # Detect current TBC phase
│   ├── import-items.py         # One-time: WowSims → SQLite
│   ├── enrich-items.py         # One-time: Wowhead source classification
│   ├── enrich-boss-drops.py    # One-time: boss loot table mapping
│   └── enrich-tier-tokens.py   # One-time: tier token → boss mapping
├── data/
│   ├── boss_strats.json        # Boss strategy database
│   └── weights/                # 26 spec weight files
├── hooks/
│   └── wow-commands/           # Optional message logging hook
├── workspace-templates/        # OpenClaw workspace files
├── setup.sh                    # One-command setup
└── README.md
```

## Adding a Spec

Create `data/weights/<spec_name>.json`. See existing files for format. Then use: `!gearprio CharName Raid`

## Adding a Boss

Add an entry to `data/boss_strats.json` with name, raid, phase, type, aliases, summary, abilities, killers, prep, and tips. Then use: `!strat BossName`

## When a New Phase Drops

```bash
curl -sL "https://raw.githubusercontent.com/wowsims/tbc/master/sim/core/items/all_items.go" -o /tmp/all_items.go
python3 scripts/import-items.py
python3 scripts/enrich-items.py
python3 scripts/enrich-boss-drops.py
python3 scripts/enrich-tier-tokens.py
# Add new bosses to data/boss_strats.json
```

## Lessons Learned

- **7B models can't follow complex instructions.** Keep AGENTS.md to a command table and nothing else.
- **Qwen 2.5 7B is the only tested model that reliably calls OpenClaw's exec tool.**
- **OpenClaw sessions persist model config.** Must clear session files when changing models.
- **OpenClaw's `before_dispatch` hook doesn't fire for user-created hooks** (as of v2026.4.2). Commands go through the LLM's exec tool, not hooks.
- **Qwen 2.5 is bilingual and will code-switch to Chinese.** Pin English in SOUL.md.

## Dependencies

Python 3.8+ (stdlib only), curl, bash, Ollama, OpenClaw. No pip packages, no Docker.

## License

MIT
