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

## Deploying

The deploy is **two stages** (`deploy.yml`): GitHub's runners build the image
and push it to GHCR, then the VM just *pulls* it. The 1 GB e2-micro never runs
`docker build` — that repeatedly OOM-thrashed and hit the job timeout.

1. **build** — `docker/build-push-action` builds and pushes
   `ghcr.io/<owner>/brnzybot:latest` and `:<sha>` (with layer caching).
2. **deploy** — checks the VM is reachable, SSHes in, syncs the repo (for the
   compose/litellm files), restores `~/brnzybot.env` → `.env`, `docker login`s to
   GHCR with the workflow token, then `docker compose pull && docker compose up -d`
   pinned to the new `:<sha>` image. Finally it health-checks `:8081/health`.

- **Automatic:** push to `master`.
- **Manual:** Actions → *Deploy to GCE* → **Run workflow** (`workflow_dispatch`).

If the VM is down, the deploy fails fast at the reachability check with a clear
`GCE VM is not reachable` error rather than a cryptic SSH timeout.

> **GHCR access:** the deploy logs the VM into GHCR with the Actions token each
> run, so a private package works out of the box. If you'd rather skip the login,
> set the `brnzybot` package's visibility to **Public** (GitHub → your profile →
> Packages) and the VM can pull anonymously.

Deterministic mode only pulls/starts the `brnzybot` container. To run the LLM
proxy too, set `ENABLE_LLM=true` in `~/brnzybot.env`, add `ANTHROPIC_API_KEY`,
and start it with the profile:
```bash
docker compose --profile llm up -d   # litellm image is pulled, not built
```

## Health & monitoring

- Liveness: `curl -sf http://localhost:8081/health` → `{"status":"ok"}`.
- Logs: `docker compose logs -f brnzybot`, and `~/brnz/openclaw-logs/brnzybot.log`.
- Container state: `docker compose ps`.

## Operating on a free-tier e2-micro

The box has **1 vCPU and 1 GB RAM**. Keep it healthy:

- **The build runs in CI, not on the box** (see above), so the e2-micro only
  ever pulls layers. Don't add deps that build from source, and don't pull the
  large `litellm` image unless you're running the LLM layer.
- **Add swap** as a safety net for the bot's own runtime memory (scipy import +
  the optimizer on top of Docker can be tight on 1 GB):
  ```bash
  sudo fallocate -l 1G /swapfile && sudo chmod 600 /swapfile
  sudo mkswap /swapfile && sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
  ```
- **Keep `ENABLE_LLM=false`** in production unless you specifically need the
  conversational features — it avoids the proxy container and all outbound model
  calls.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `GCE VM is not reachable on port 22` | the instance is stopped or wedged — `gcloud compute instances list`, then `reset`/`start` it |
| `docker compose pull` fails with auth error | GHCR login failed — confirm the workflow has `packages: write`, or set the package visibility to Public |
| Health check fails after deploy | container crashed on boot — check `docker compose logs`; confirm port 8081 is published |
| `~/brnzybot.env is missing` | create the secrets file on the VM (step 3) |
| Gear commands say "can't locate gear data" | databases not built into the data volume (step 4) |
| `/strat` does nothing / cog fails to load | check logs for a startup import error; CI byte-compile should catch syntax issues pre-merge |
</content>
