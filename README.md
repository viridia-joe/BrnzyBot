# BrnzyBot

A Discord bot for World of Warcraft **TBC Classic** raid teams. It computes
EP-based gear recommendations from a local item database, pulls live gear from
Warcraft Logs, serves boss strategies, generates raid assignments, and runs a
few guild utilities (subscriptions, a 1v1 betting minigame).

The bot is **deterministic-first**: every core command runs on local data
(SQLite + a MIP optimizer) with no LLM in the loop. An optional conversational
layer (natural-language routing, free-form Q&A, AI raid assignments) can be
switched on with a single flag. See [Runtime modes](#runtime-modes).

> **Maintained by code assistants.** If you're an AI assistant working in this
> repo, start with [`CLAUDE.md`](CLAUDE.md) — it has the architecture map,
> conventions, and gotchas you need before editing.

---

## Commands

All commands are available as Discord **slash commands**; the most common ones
also have `!` prefix aliases.

### Gear
| Command | What it does |
|---|---|
| `/gearprio <character> [spec] [phase]` | Ranked upgrade priority list (EP-net, with source) |
| `/gearcheck <character> [spec] [phase]` | Head-to-toe gear vs BiS, with hit-cap and set-bonus analysis |
| `/simexport <character> [spec] [phase]` | Export a WowSims-importable JSON from the character's latest WCL gear |

### Strategy & raid
| Command | What it does |
|---|---|
| `/strat <boss or question>` | Boss strategy: phases, abilities, role notes |
| `/abilities <boss>` | List a boss's abilities and mechanics |
| `/bossguide <boss> [roster image]` | WoW-ready `/ra` raid assignments + a position diagram |

### Guild admin (requires *Manage Guild*)
`/setup realm <slug> [region]`, `/setup officerole`, `/setup botduellog`,
`/verbosity <mode> [channel]`, `/response <target> [channel]`,
`/addchar`, `/removechar`, `/listchars`, `/listspecs`.

### Subscriptions & data (GDPR)
`/subscribe`, `/subscription`, `/cancel`, `/setweights`, `/myweights`,
`/clearweights`, `/deletedata`, `/deletemydata`.

### BotDuel (Crashin' Thrashin' Robot 1v1 betting)
`/botduel challenge|accept|decline|result|confirm|dispute|status|leaderboard|record`,
plus officer-only `/botduel resolve|adjust`.

---

## Runtime modes

The bot reads one master switch, **`ENABLE_LLM`** (default `false`):

- **Deterministic mode (`ENABLE_LLM=false`)** — the default, and what the
  free-tier GCP box runs. The optimizer, gear lists, strategy lookups, and
  boss-guide templates all work with no model and no network calls to any LLM.
  Natural-language chat and free-form Q&A degrade to a short "use a command"
  hint. **No `ANTHROPIC_API_KEY` and no litellm container are needed.**
- **LLM mode (`ENABLE_LLM=true`)** — adds the conversational layer: NL intent
  routing, free-form WoW Q&A, prose annotation on `/gearprio`, narrated
  strategy answers, and AI-generated raid assignments (incl. roster screenshot
  parsing). Requires the LiteLLM proxy (`docker compose --profile llm up -d`)
  and `ANTHROPIC_API_KEY`.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the exact LLM-dependency
map.

---

## Quick start (local)

Requirements: **Python 3.11**, the deps in [`requirements.txt`](requirements.txt)
(`discord.py`, `scipy`, `numpy`, `Pillow`), and a
[Warcraft Logs v2 API client](https://www.warcraftlogs.com/api/docs).

```bash
git clone https://github.com/viridia-joe/BrnzyBot.git
cd BrnzyBot
pip install -r requirements.txt

cp .env.example ~/.openclaw/data/.env   # then fill in the required values

# Build the local databases (item DB, strategy DB) into the data dir:
python3 scripts/import-items.py     # → tbc_items.db
python3 build_strategy_db.py        # → tbc_strategy.db

python3 bot.py
```

Required environment variables (see [`.env.example`](.env.example) for the full
list): `DISCORD_BOT_TOKEN`, `WCL_CLIENT_ID`, `WCL_CLIENT_SECRET`. `ANTHROPIC_API_KEY`
is only needed when `ENABLE_LLM=true`.

### Run with Docker

```bash
docker compose up --build -d                 # deterministic mode (bot only)
docker compose --profile llm up --build -d   # also start the LiteLLM proxy
```

The bot exposes a liveness endpoint at `http://localhost:8081/health`.

---

## Deployment

Production runs on a **Google Compute Engine `e2-micro`** (free tier),
provisioned by Terraform and deployed by GitHub Actions on every push to
`master`. The full runbook — including the one-time step of building the
databases into the data volume — is in
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

**New to this and setting it up for the first time?** Follow the start-from-zero
guide: [`docs/SETUP_OPERA_WIPE_SOCIETY.md`](docs/SETUP_OPERA_WIPE_SOCIETY.md) —
Discord app → GCP VM → live bot, with nothing assumed.

---

## Repository layout

```
bot.py                 — entry point: logging, health server, cog loading
config.py              — env vars, paths, ENABLE_LLM flag, model routing
cogs/                  — Discord command surface (one cog per feature area)
core/                  — pure logic: optimizer, WCL client, caches, handlers
db/                    — per-server config SQLite (schema + accessors)
data/                  — version-controlled static data (spec weights, gems, …)
scripts/               — one-off DB build/enrichment + standalone CLI tools
terraform/             — GCP infrastructure (VM, static IP, firewall)
docker-compose.yml     — bot + optional litellm proxy
.github/workflows/     — ci.yml (checks) and deploy.yml (GCE deploy)
docs/                  — ARCHITECTURE.md, DEPLOYMENT.md
CLAUDE.md              — guide for code assistants maintaining this repo
```

> **Legacy:** `workspace-templates/` and `hooks/` date from an earlier design
> where the bot ran inside [OpenClaw](https://github.com/openclaw/openclaw) with
> a local Ollama model. The current bot is a standalone `discord.py` process and
> does not use them. They're kept for reference; see `CLAUDE.md`.

## License

MIT
</content>
</invoke>
