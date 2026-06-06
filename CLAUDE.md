# CLAUDE.md — guide for code assistants

Discord bot for WoW TBC Classic raids. Deterministic core (SQLite + MIP gear optimizer) with an optional LLM layer. See [`README.md`](README.md), [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## Golden rules

1. **Keep core commands deterministic.** `/gearprio`, `/gearcheck`, `/strat`, `/abilities`, `/simexport`, `/rotationcheck`, `/audit`, and all admin/billing/botduel commands must work with `ENABLE_LLM=false`. If a feature needs LLM, gate it on `entitlements.llm_enabled(guild_id)` and provide a deterministic fallback. Grep `if not config.ENABLE_LLM:` to match the pattern.
2. **Target Python 3.11.** Docker base is `python:3.11-slim`. No backslashes inside f-string expressions — that's 3.12-only and crashes at import. CI byte-compiles the whole tree.
3. **No heavy dependencies.** Bot runs on a 1 GB e2-micro. Every dep needs a manylinux cp311 wheel. LLM calls go over plain HTTP — no LLM SDK in `requirements.txt`.
4. **Handlers return strings, cogs post them.** `core/*_handler.py` returns Discord-ready text, never calls Discord APIs. Cogs own all I/O.
5. **Secrets never committed.** `.env`, `*.db`, `terraform/*.tfvars` are gitignored. Config lives in `~/.openclaw/data/.env` locally and `~/brnzybot.env` on the VM.
6. **Never run `scripts/build_baselines.py` in CI.** It uses WCL credentials and writes to `data/baselines/`. Run manually on the VM only.

## Architecture

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
        gear_reasoning / *_handler ──(llm_enabled)──▶ LiteLLM proxy ▶ Claude
                                     └─ else: deterministic fallback
```

- **`bot.py`** — boots logging, `/health` HTTP server (port `HEALTH_PORT`, default 8081), loads cogs.
- **`config.py`** — single source for env vars, paths, `ENABLE_LLM` flag, model names. Always `import config`.
- **`cogs/`** — one cog per feature: `gear`, `rotation`, `strategy`, `bossguide`, `listener`, `admin`, `billing`, `onboarding`, `simexport`, `botduel`, `heartbeat`, `audit`.
- **`core/`** — pure logic. Key: `gear_optimizer.py` (MIP), `wcl_client.py` + `gear_cache.py`, `rotation_handler.py` (profiles in `data/rotations/`), `classifier.py` (intent parsing), `entitlements.py` (LLM/Pro gating), `fight_diagrams.py`, `messages.py`.
- **`db/`** — SQLite `brnzybot.db` (verbosity, characters, realm, intents, rate limits). Schema in `db/schema.sql`.
- **`data/`** — static data (weights, gems, set bonuses, rotation profiles, baselines, diagrams). Generated item/strategy DBs are gitignored.

## LLM gating

Gates now check **`core/entitlements.py:llm_enabled(guild_id)`** = `config.ENABLE_LLM AND is_pro(guild_id)`. Pass `guild_id` through to handlers; use `"global"` when no guild context. When `ENABLE_LLM=false` (current prod default), all gates are always False.

| Site | Off-mode behavior |
|---|---|
| `core/classifier.py:classify` | Skip LLM triage; return `Intent.unknown` |
| `core/gear_reasoning.py:annotate` | Return deterministic optimizer skeleton |
| `core/strategy_handler.py` | Return rendered strategy context block |
| `core/general_handler.py` | Return "use a command" hint |
| `core/bossguide_handler.py` | Use placeholder template; skip vision parse |
| `core/node_health.py:check_nodes` | Return empty status — **never poll 10.0.0.x** |

`node_health` polls a private GPU fleet unreachable from the cloud. Unconditional calls add seconds of timeout latency.

## Running, testing, deploying

```bash
# Local
python3 bot.py                    # needs ~/.openclaw/data/.env + built DBs
docker compose up --build

# Before pushing
python3 -m compileall -q .
python3 tests/test_audit.py

# Offline (no creds needed)
python3 -m tools.audit_cli --fixtures SYNTHLOG00000001        # whole roster
python3 -m tools.audit_cli --fixtures SYNTHLOG00000001 Pyra   # one raider
```

Fixture data: `tests/fixtures/` (synthetic WCL logs + item DB). `tools/make_synthetic_fixtures.py` regenerates them. `tools/capture_wcl.py` captures real logs (needs WCL creds).

**Deploy:** push to `master` → GitHub Actions SSHes to GCE VM → `docker compose up --build -d`. Health check curls `localhost:8081/health`. Manual trigger via Actions `workflow_dispatch`.

## Known legacy

- `workspace-templates/`, `hooks/` — unused (prior Ollama design). Safe to ignore.
- `core/triage.py` — superseded by `core/classifier.py`. References legacy local-model config.
- `config.LITELLM_BASE_URL` default (`10.0.0.186`) and `node_health` IPs — old LAN cluster, overridden in cloud.

When in doubt, prefer the smallest change that keeps deterministic mode working on the 1 GB box.
