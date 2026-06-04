# Architecture

BrnzyBot is a standalone `discord.py` process. Commands flow from Discord into
**cogs** (which own all Discord I/O), then into **core** logic (pure functions
that return strings), backed by **SQLite** databases and the **Warcraft Logs**
API. An optional LLM layer sits behind the `ENABLE_LLM` flag.

## Request flow

```
Discord event
  │
  ├─ slash command ────────────────▶ cogs/<feature>.py
  │                                     │  (defer, rate-limit, resolve character)
  │                                     ▼
  │                                  core/<feature>_handler.py  ── returns str ──▶ cog posts it
  │
  └─ message (no prefix) ──▶ cogs/listener.py
                               │  verbosity gate (per guild+channel)
                               ▼
                            core/classifier.py:classify()
                               │  1) deterministic parse (always)
                               │  2) LLM triage  ── only if ENABLE_LLM ──▶ LiteLLM proxy
                               ▼
                            dispatch to the matching handler
```

## Layers

| Layer | Dir | Responsibility | Talks to Discord? |
|---|---|---|---|
| Entry | `bot.py` | logging, `/health` server, cog loading, error handling | yes (client) |
| Config | `config.py` | env vars, paths, `ENABLE_LLM`, model names | no |
| Commands | `cogs/` | parse args, rate-limit, defer, chunk & post | **yes** |
| Logic | `core/` | optimizer, WCL, caches, context builders, handlers | **no** (returns strings) |
| State | `db/` | per-server config in `brnzybot.db` | no |
| Static data | `data/` | spec weights, gems, set bonuses, strategy JSON | no |

## Data stores

Runtime databases live in `DATA_DIR` (`~/.openclaw/data`), bind-mounted on the
VM. They are **generated and gitignored** — they are not in the repo or the
Docker image, so they must be built into the data volume (see DEPLOYMENT.md).

| File | Built by | Used for |
|---|---|---|
| `tbc_items.db` | `scripts/import-items.py` (+ `enrich-*`) | item stats, EP, sources |
| `tbc_strategy.db` | `build_strategy_db.py` | boss strategy FTS lookups |
| `brnzybot.db` | `db/server_config.py:init_db()` (auto) | per-server config, characters, usage |
| `manifest.db` | `core/manifest.py` | data version tracking |

Static spec weight files in `data/weights/*.json` (26 specs) drive EP
calculation; `data/strategy/` seeds the strategy DB.

## The gear pipeline (fully deterministic)

1. `core/gear_cache.py:get_gear()` returns a gear snapshot — live from Warcraft
   Logs via `core/wcl_client.py`, or from the local cache when WCL is down.
2. `core/gear_context.py:build_context()` computes hit cap, active set bonuses,
   per-slot EP from the spec weight file.
3. `core/gear_optimizer.py` solves a MIP (`scipy`) for upgrades / BiS.
4. `core/gear_handler.py` formats the result:
   - `/gearcheck` → `handle_gear_list()` — head-to-toe vs BiS. **Never uses an LLM.**
   - `/gearprio` → `handle_gear_question()` — builds a ranked skeleton, then
     `gear_reasoning.annotate()` either narrates it (LLM on) or returns it as-is.

## LLM-dependency map

Everything works in deterministic mode; the table shows what the LLM *adds*.

| Feature | Deterministic result (ENABLE_LLM=false) | With LLM |
|---|---|---|
| `/gearprio` | Ranked upgrade list (slot, from→to, net EP, source) | + prose: where to farm, set-bonus notes |
| `/gearcheck` | Full BiS comparison | identical (never used an LLM) |
| `/strat`, `/abilities` | Rendered strategy/ability block from the DB | narrated, question-focused answer |
| `/bossguide` | Placeholder `/ra` template + position diagram | names filled from roster; tailored assignments; screenshot parsing |
| NL chat / @mention | "use a command" hint | intent routing + free-form Q&A |
| `/simexport`, billing, admin, botduel | full functionality | identical |

The LLM is reached only over HTTP (OpenAI-compatible) at `LITELLM_BASE_URL`. The
LiteLLM proxy (`litellm_config.yaml`) maps the `gear-*` model aliases to Claude
tiers. The bot image contains **no** LLM SDK.

> Historical note: the proxy originally fronted a LAN Ollama GPU cluster (see the
> node IPs in `core/node_health.py`); the cloud deployment routes the aliases to
> the Claude API instead.

## Deployment topology

```
GitHub (push to master)
      │  Actions: deploy.yml  (SSH)
      ▼
GCE e2-micro VM (Ubuntu 22.04, Docker)
   docker compose:
     brnzybot   ← built from this repo, port 8081 health published
     litellm    ← optional, behind the "llm" profile
   volumes: /home/brnz/openclaw-{data,logs}
```

See [`DEPLOYMENT.md`](DEPLOYMENT.md) for provisioning and operations.
</content>
