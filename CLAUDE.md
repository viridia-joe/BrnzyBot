# CLAUDE.md — guide for code assistants

This repo is maintained primarily by AI coding assistants. Read this before
editing. It captures the architecture, the non-obvious constraints, and the
conventions that keep changes safe.

## What this is

A standalone `discord.py` bot for WoW TBC Classic raid teams. Deterministic core
(SQLite + a MIP gear optimizer) with an **optional** LLM layer behind a flag.
User-facing overview is in [`README.md`](README.md); deeper design in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md); ops in
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## Golden rules

1. **Keep core commands deterministic.** `/gearprio`, `/gearcheck`, `/strat`,
   `/abilities`, `/simexport`, `/rotationcheck`, and all admin/billing/botduel
   commands must work with `ENABLE_LLM=false` and **no** network calls to any
   model. (`/rotationcheck` calls WCL for cast data, but its anomaly report is
   fully deterministic; the LLM "coach" paragraph is gated on `ENABLE_LLM`.) If you add a
   feature that needs an LLM, gate it on `config.ENABLE_LLM` and provide a
   deterministic fallback. Grep for existing `if not config.ENABLE_LLM:` guards
   to match the pattern.
2. **Target Python 3.11.** The Docker base is `python:3.11-slim`. Do **not** use
   3.12-only syntax. In particular, **no backslashes inside f-string
   expressions** (`f"{d['x']}"` with escaped quotes is a 3.12-only thing and
   will crash at import on 3.11). CI byte-compiles the whole tree to catch this.
3. **Don't add heavy dependencies.** The bot runs on a 1 GB free-tier e2-micro.
   Every dep must ship a manylinux cp311 wheel (no compile step in the
   Dockerfile). The bot talks to the LLM proxy over plain HTTP — do not add an
   LLM SDK to `requirements.txt`.
4. **Handlers return strings, cogs post them.** `core/*_handler.py` functions
   return Discord-ready text (and never call Discord APIs). Cogs own all
   `interaction`/`ctx` I/O. Keep that separation.
5. **Secrets never get committed.** `.env`, `*.db`, and `terraform/*.tfvars` are
   gitignored. Real config lives in `~/.openclaw/data/.env` locally and in
   `~/brnzybot.env` on the VM.

## Architecture in one screen

```
Discord ──▶ bot.py ──▶ cogs/*           (command surface, all I/O)
                          │
                          ▼
                       core/*           (pure logic, returns strings)
             ┌────────────┼─────────────┐
             ▼            ▼              ▼
        gear_optimizer  wcl_client   strategy_context   ← deterministic
        (scipy MIP)     (HTTP→WCL)   (SQLite FTS)
             │
             ▼
        gear_reasoning / *_handler ──(ENABLE_LLM)──▶ LiteLLM proxy ▶ Claude
                                     └─ else: deterministic fallback
```

- **`bot.py`** — boots logging, a `/health` HTTP server (port `HEALTH_PORT`,
  default 8081), and loads the cogs in `setup_hook`.
- **`config.py`** — the single source of env vars, filesystem paths, the
  `ENABLE_LLM` flag, and model routing names. Import it as `import config`.
- **`cogs/`** — one cog per feature: `gear`, `rotation`, `strategy`, `bossguide`,
  `listener` (NL gate), `admin`, `billing`, `onboarding`, `simexport`,
  `botduel`. Registered in `bot.py:setup_hook`.
- **`core/`** — pure logic. Notable: `gear_optimizer.py` (the MIP solver),
  `gear_handler.py` / `gear_reasoning.py`, `wcl_client.py` + `gear_cache.py`,
  `rotation_handler.py` (cast-by-cast anomaly check; profiles in `data/rotations/`),
  `classifier.py` (intent parsing — deterministic first, LLM fallback),
  `strategy_context.py` / `strategy_handler.py`, `bossguide_*`, `node_health.py`.
- **`db/`** — per-server config in `brnzybot.db` (verbosity, characters, realm,
  pending intents, usage/rate limits). Schema in `db/schema.sql`.
- **`data/`** — version-controlled static data (spec weight files, gems, set
  bonuses, strategy source JSON). The large item/strategy **databases are
  generated, gitignored**, and built by the `scripts/` and `build_*.py` tools.

## The ENABLE_LLM flag — where it's gated

LLM sites now gate on **`core/entitlements.py:llm_enabled(guild_id)`**, which is
`config.ENABLE_LLM AND is_pro(guild_id)` (plus a monthly cost cap). Pass the
`guild_id` through to the handler so paid (Pro) guilds get the LLM enhancement and
free guilds get the deterministic output. A caller with no guild context passes
`"global"`, which falls back to the old `ENABLE_LLM`-only behavior. Crucially,
when `ENABLE_LLM` is false (today's prod default) `llm_enabled` is always False —
so every gate behaves exactly as before until an LLM backend is turned on.

When you touch model-backed code, these are the existing chokepoints:

| Site | Off-mode behavior |
|---|---|
| `core/classifier.py:classify` | Skip LLM triage; return `Intent.unknown` |
| `core/gear_reasoning.py:annotate` | Return the deterministic optimizer skeleton |
| `core/strategy_handler.py` | Return the rendered strategy context block |
| `core/general_handler.py` | Return a "use a command" hint |
| `core/bossguide_handler.py` | Use the placeholder template; skip vision parse |
| `core/node_health.py:check_nodes` | Return empty status; **don't poll the LAN** |

`node_health` is important: it polls a private GPU fleet at `10.0.0.x` that is
unreachable from the cloud. Never call it unconditionally — it must stay behind
the flag or it adds seconds of timeout latency to every gear/strategy command.

## Running, testing, deploying

- **Run locally:** `python3 bot.py` (needs `~/.openclaw/data/.env` and the built
  databases — see DEPLOYMENT.md). Or `docker compose up --build`.
- **Checks:** CI (`.github/workflows/ci.yml`) byte-compiles every `.py` on
  Python 3.11, import-checks the deterministic modules, and runs the audit test
  harness. **Before pushing, run:**
  ```bash
  python3 -m compileall -q .
  python3 tests/test_audit.py          # plain-asserts harness (no pytest needed)
  ```
  If you add tests, put them under `tests/` and wire them into `ci.yml`.
- **Offline (no creds / no network) dev & test.** The WCL-backed features
  (`/audit`, `/rotationcheck`, gear auto-register) can run with zero credentials:
  - `core/wcl_client.py` replays canned JSON from `WCL_FIXTURE_DIR` instead of
    calling the API (env-gated; no effect in prod).
  - The full TBC item DB ships as a committed fixture (`tests/fixtures/items/
    tbc_items.db.gz`, ~330 KB); `tools.fixtures.ensure_item_db()` materialises it.
  - `tools/make_synthetic_fixtures.py` writes an example log covering every P1–P2
    boss; `tools/capture_wcl.py` (needs creds) captures **real** logs into the
    same fixture format.
  - Run the whole pipeline from the shell:
    ```bash
    python3 -m tools.audit_cli --fixtures SYNTHLOG00000001          # whole roster
    python3 -m tools.audit_cli --fixtures SYNTHLOG00000001 Pyra     # one raider
    ```
- **Deploy:** pushing to `master` triggers `.github/workflows/deploy.yml`, which
  SSHes to the GCE VM and runs `docker compose up --build -d`. The health step
  curls `localhost:8081/health`. Deploy can also be run manually via the Actions
  "Run workflow" button (`workflow_dispatch`).

## Conventions

- Match the surrounding style: module docstring with a short "Pipeline"/"Flow"
  section, `log = logging.getLogger(__name__)`, type hints, `from __future__
  import annotations` in cogs.
- Keep cogs as thin dispatch; put logic in `core/`.
- Discord messages are chunked to 2000 chars via `cogs/gear.py:_chunks`.
- Spec names are canonical keys (e.g. `destro_warlock`); user input is resolved
  through `core/classifier.py:SPEC_ALIASES` / `VALID_SPECS`.
- Don't commit `model_id`/internal identifiers, secrets, or generated `*.db`.

## Known cleanup / legacy (don't be surprised)

- **`workspace-templates/` and `hooks/`** are from the prior OpenClaw + local
  Ollama design and are unused by the standalone bot. Safe to ignore; propose
  removal only with the maintainer's OK.
- **`core/triage.py`** is an older intent path superseded by `core/classifier.py`
  (the listener uses `classifier`). It references the legacy local-model config.
- **`config.LITELLM_BASE_URL` default** (`10.0.0.186`) and `node_health`'s node
  IPs reflect the old LAN cluster; in the cloud they're overridden/unused.
- **`README.md`/`BACKLOG.md`** reference some `!`-prefixed commands; slash
  commands are the primary surface now.

When in doubt, prefer the smallest change that keeps deterministic mode working
on the 1 GB box.
</content>
