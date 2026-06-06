# Deployment runbook

Production runs on a **Google Compute Engine `e2-micro`** (free-tier) instance,
provisioned with Terraform and deployed by GitHub Actions on every push to
`master`. The bot runs in **deterministic mode** (`ENABLE_LLM=false`) by default
to stay within the box's 1 GB of RAM.

## Topology

- **VM:** `e2-micro`, Ubuntu 22.04, 20 GB disk, static external IP — all defined
  in `terraform/`. Free-tier eligible in `us-central1` / `us-east1` / `us-west1`.
- **Firewall:** only port 22 (SSH) is open. The health endpoint is reached over
  the SSH tunnel by CI; it is not exposed publicly.
- **Containers:** `docker compose` runs `brnzybot` (always) and, behind the `llm`
  profile, the `litellm` proxy (only when the LLM layer is enabled).
- **Persistence:** `~/brnz/openclaw-data` and `~/brnz/openclaw-logs` are
  bind-mounted into the container. Secrets live in `~/brnzybot.env` (outside the
  repo, survives `git reset`).

## One-time provisioning

1. **Create the VM** (from `terraform/`):
   ```bash
   cp terraform.tfvars.example terraform.tfvars   # set project_id + ssh_public_key
   terraform init && terraform apply              # outputs the static IP
   ```
2. **GitHub repo secrets** (Settings → Secrets → Actions):
   - `GCE_HOST` — the static IP from the Terraform output
   - `GCE_USER` — the SSH user (default `brnz`)
   - `GCE_SSH_KEY` — the matching **private** key
3. **Secrets file on the VM** — create `~/brnzybot.env` from
   [`.env.example`](../.env.example). At minimum:
   `DISCORD_BOT_TOKEN`, `WCL_CLIENT_ID`, `WCL_CLIENT_SECRET`, `HOME_GUILD_ID`.
   Leave `ENABLE_LLM=false` unless you intend to run the LLM layer.
   > The deploy fails fast with a clear error if this file is missing.
4. **Build the databases into the data volume.** The item/strategy DBs are
   gitignored and **not** in the image, so the bot can't do gear/strategy lookups
   until they exist in `~/brnz/openclaw-data`. Build them once on the VM (or build
   locally and `scp` them in):
   ```bash
   # inside the repo checkout on the VM, with deps available:
   python3 scripts/import-items.py        # → tbc_items.db
   python3 build_strategy_db.py           # → tbc_strategy.db
   # move/confirm they live in ~/brnz/openclaw-data (DATA_DIR)
   ```
   `brnzybot.db` is created automatically on first start.

## Rolling the bot to a new content phase

When a phase ships (e.g. Phase 2 — SSC / The Eye / Ogri'la / Season 2 arena):

1. **Refresh the item DB** so newly-relevant items land with their correct phase
   (the WowSims export already tags each item's phase; the enrich pass adds source
   labels, including name-prefix labels for the PvP arena sets):
   ```bash
   curl -s https://raw.githubusercontent.com/wowsims/tbc/master/sim/core/items/all_items.go -o /tmp/all_items.go
   python3 scripts/import-items.py
   python3 scripts/enrich-boss-drops.py
   ```
2. **Flip each guild forward** in Discord: `/setup phase 2`. The optimizer then
   considers Phase 1 **and** 2 gear, so still-BiS Phase-1 pieces stay in the pool
   (shown with 🥇 in `/gearcheck`, vs 🔥 for current-tier BiS).

Rated **arena** gear is considered in BiS by default (battleground honor gear is
not). Arena participation is a personal call, so it's a per-command toggle, not a
guild setting: anyone who doesn't do arena can pass `arena:false` on their own
`/gearcheck` or `/gearprio` to exclude it.

## Deploying

- **Automatic:** push to `master`. `deploy.yml` SSHes in, `git reset --hard`,
  restores `~/brnzybot.env` → `.env`, runs `docker compose up --build -d`, then
  health-checks `http://localhost:8081/health`.
- **Manual:** Actions → *Deploy to GCE* → **Run workflow** (`workflow_dispatch`).

Deterministic mode only builds/starts the `brnzybot` container. To run the LLM
proxy too, set `ENABLE_LLM=true` in `~/brnzybot.env`, add `ANTHROPIC_API_KEY`,
and start it with the profile:
```bash
docker compose --profile llm up --build -d
```

## Running a second instance (e.g. a prod bot on your guild's Discord)

Each instance is a standalone bot for **one** Discord. Code is per-instance by
env + per-guild by its own `brnzybot.db`, so two instances are fully isolated.
To stand up a second one alongside the dev bot:

1. **New Discord app + bot token** at the Discord developer portal → its own
   `DISCORD_BOT_TOKEN` and `HOME_GUILD_ID`. (Separate tokens = separate Discord
   rate-limit buckets, so no contention there.)
2. **Use a separate WCL API client** for the new instance (register a second app
   on Warcraft Logs). The WCL rate limiter in `core/wcl_client.py` is
   per-process, so two instances sharing one `WCL_CLIENT_ID` would burn the
   shared point budget twice as fast with no coordination. Separate clients =
   independent budgets.
3. **Provision its VM** with a distinct name so resources don't collide:
   ```bash
   # in a fresh terraform.tfvars (or a second working dir):
   instance_name = "brnzybot-prod"
   # NOTE: GCP's free tier covers ONE e2-micro per account — a second VM is billed
   # (~$6/mo) unless you co-locate (tight on 1 GB). See the LLM tier for sizing.
   terraform apply
   ```
4. **Create `~/brnzybot.env`** on the new VM with that instance's token + WCL
   client, then **build the DBs** (`scripts/import-items.py`, `build_strategy_db.py`).
5. **Deploy to it:** Actions → *Deploy to GCE* → **Run workflow**, and set the
   `host` (and `user` if different) inputs to the new VM. (Reuse the same
   `GCE_SSH_KEY` across VMs, or add a second key + workflow.) Push-to-master
   keeps deploying the dev instance via the `GCE_HOST`/`GCE_USER` secrets.

| Resource | Per-instance | Shareable |
|---|---|---|
| Discord token, `brnzybot.db`, WCL client | ✅ separate | — |
| `tbc_items.db` / `tbc_strategy.db` (read-only) | rebuilt per VM | ✅ (or shared mount) |
| LiteLLM proxy (only if `ENABLE_LLM`) | — | ✅ one proxy serves both |

## Health & monitoring

- Liveness: `curl -sf http://localhost:8081/health` → `{"status":"ok"}`.
- Logs: `docker compose logs -f brnzybot`, and `~/brnz/openclaw-logs/brnzybot.log`.
- Container state: `docker compose ps`.

## Operating on a free-tier e2-micro

The box has **1 vCPU and 1 GB RAM**. Keep it healthy:

- **Builds are the tight spot.** The image installs only wheel-based deps
  (`numpy`/`scipy`/`Pillow`/`discord.py`) — no compile toolchain. Don't add deps
  that build from source, and don't pull the large `litellm` image unless you're
  running the LLM layer.
- **Add swap** if builds or `scipy` import get OOM-killed:
  ```bash
  sudo fallocate -l 1G /swapfile && sudo chmod 600 /swapfile
  sudo mkswap /swapfile && sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
  ```
- **Prefer pulling a prebuilt image** over building on the VM if build time
  becomes a problem: build/push in CI (e.g. to GHCR) and have the VM `pull`
  instead of `--build`. This is the recommended next optimization if the
  on-VM `docker build` is slow or memory-pressured.
- **Keep `ENABLE_LLM=false`** in production unless you specifically need the
  conversational features — it avoids the proxy container and all outbound model
  calls.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Deploy step hangs ~30 min then cancels | `docker build` starved on the e2-micro — add swap or switch to a prebuilt image (see above) |
| Health check fails after deploy | container crashed on boot — check `docker compose logs`; confirm port 8081 is published |
| `~/brnzybot.env is missing` | create the secrets file on the VM (step 3) |
| Gear commands say "can't locate gear data" | databases not built into the data volume (step 4) |
| `/strat` does nothing / cog fails to load | check logs for a startup import error; CI byte-compile should catch syntax issues pre-merge |
</content>
