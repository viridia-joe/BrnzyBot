# Setting up BrnzyBot for the Opera Wipe Society Discord

A complete, **start-from-nothing** walkthrough: from "I have a Discord server and
a GitHub copy of this repo" to "the bot answers `/gearcheck` in Opera Wipe
Society." No prior work on this project is assumed.

By the end you'll have:

- A Discord **bot application** (its own token) invited into Opera Wipe Society.
- A free **Google Cloud** VM running the bot 24/7, auto-deployed from `master`.
- The bot running in **deterministic mode** (`ENABLE_LLM=false`) — every gear,
  strategy and raid command works with **no AI key and no extra cost**.

> **Time:** ~45–60 min the first time, most of it waiting on cloud provisioning.
> **Cost:** $0 if you stay on the GCP free-tier `e2-micro` in a US region.

If you'd rather not touch cloud infra at all, jump to
[Appendix A: run it on any Docker host](#appendix-a-run-it-on-any-docker-host-no-gcp)
— same bot, you just supply the machine.

---

## What you're building

```
   You push to master ─▶ GitHub Actions ─SSH▶ GCP e2-micro VM
                                                 └─ docker compose up ─▶ brnzybot
                                                        │
   Opera Wipe Society Discord ◀──── slash commands ─────┘
                                                        │
                            Warcraft Logs API ◀── live gear lookups
```

The bot is a single container. Its config lives in a secrets file **on the VM**
(`~/brnzybot.env`, never in git). Two read-only databases (items, strategies)
get built once onto the VM's data disk.

---

## Accounts you'll need (gather these first)

| Account | Used for | Cost |
|---|---|---|
| **Discord** (you already own the Opera Wipe Society server, with *Manage Server*) | Create the bot, invite it | Free |
| **Warcraft Logs** | v2 API client for live gear lookups | Free |
| **GitHub** (your fork/clone of this repo) | Stores code, runs the deploy workflow | Free |
| **Google Cloud Platform** | Hosts the VM | Free tier (one `e2-micro`) |

You'll also need these tools on **your own laptop**:

- [`git`](https://git-scm.com/)
- [Terraform](https://developer.hashicorp.com/terraform/install) (provisions the VM)
- The [`gcloud` CLI](https://cloud.google.com/sdk/docs/install) (authenticates Terraform to GCP)
- An SSH keypair (we'll make one in Part 4 if you don't have one)

---

## Part 1 — Create the Discord bot

1. Go to the **[Discord Developer Portal](https://discord.com/developers/applications)** → **New Application**. Name it `BrnzyBot` (or `Opera Wipe Society Bot`).
2. Left sidebar → **Bot** → **Add Bot**.
3. **Copy the token** (click *Reset Token* if needed). This is your
   `DISCORD_BOT_TOKEN` — treat it like a password, you'll paste it into the
   secrets file in Part 6.
4. **Enable the privileged intent the bot requires.** Still on the Bot page,
   scroll to **Privileged Gateway Intents** and turn **ON**:
   - ✅ **Message Content Intent** — required; the bot reads `!` commands and
     @-mentions (`bot.py` sets `intents.message_content = True`). Without it the
     bot will fail to log in.
   - Leave **Server Members Intent** and **Presence Intent** **OFF** — the bot
     doesn't use them.

### Build the invite link

1. Left sidebar → **OAuth2** → **URL Generator**.
2. Under **Scopes**, tick **`bot`** and **`applications.commands`**.
3. Under **Bot Permissions**, tick exactly these (least-privilege):
   - View Channels
   - Send Messages
   - Embed Links
   - Attach Files *(boss-guide position diagrams are image uploads)*
   - Read Message History
   - Use Application Commands
4. Copy the generated URL at the bottom — that's your **invite link**. Hold off
   on using it until the bot is actually running (Part 9); an invited-but-offline
   bot just shows as offline.

### Grab the server ID

You'll need Opera Wipe Society's numeric **guild ID** for instant slash-command
sync:

1. In Discord: **User Settings → Advanced → Developer Mode → ON**.
2. Right-click the **Opera Wipe Society** server icon → **Copy Server ID**.
3. Save it — this is `HOME_GUILD_ID`.

---

## Part 2 — Get Warcraft Logs API credentials

1. Log in at **[warcraftlogs.com](https://www.warcraftlogs.com)** → your avatar →
   **Settings → Web API**, or go straight to the
   [V2 client manager](https://www.warcraftlogs.com/api/clients/).
2. **Create a new V2 client.** Name it `BrnzyBot`; the redirect URL can be
   `https://localhost` (the bot uses client-credentials, not user login).
3. Copy the **Client ID** and **Client Secret** → these are `WCL_CLIENT_ID` and
   `WCL_CLIENT_SECRET`.

> Use a **dedicated** WCL client for this bot. The rate limiter in
> `core/wcl_client.py` is per-process, so sharing one client across bots burns
> the shared point budget twice as fast.

---

## Part 3 — Get the code onto your GitHub

This repo deploys itself from **your** GitHub repository. If you haven't already,
fork or push it to an account you control (the deploy workflow clones
`github.server_url/github.repository` automatically — no hardcoded owner). Clone
your copy locally:

```bash
git clone https://github.com/<your-account>/BrnzyBot.git
cd BrnzyBot
```

---

## Part 4 — Provision the GCP VM with Terraform

This creates a free-tier `e2-micro`, a reserved static IP, and an SSH-only
firewall rule — all defined in `terraform/`.

1. **Authenticate gcloud and pick a project** (create one in the
   [GCP Console](https://console.cloud.google.com/) if needed — note its
   **Project ID**, shown in the console header):
   ```bash
   gcloud auth application-default login
   gcloud config set project <YOUR_PROJECT_ID>
   ```
   Make sure the **Compute Engine API** is enabled for the project
   (Console → APIs & Services, or `gcloud services enable compute.googleapis.com`).

2. **Make an SSH key** if you don't have one. GitHub Actions will use the
   **private** half to deploy; the VM gets the **public** half.
   ```bash
   ssh-keygen -t ed25519 -C "brnzybot-deploy" -f ~/.ssh/brnzybot_deploy
   # creates ~/.ssh/brnzybot_deploy (private) and ~/.ssh/brnzybot_deploy.pub (public)
   ```

3. **Fill in Terraform variables:**
   ```bash
   cd terraform
   cp terraform.tfvars.example terraform.tfvars
   ```
   Edit `terraform.tfvars`:
   ```hcl
   project_id     = "<YOUR_PROJECT_ID>"
   ssh_public_key = "ssh-ed25519 AAAA... brnzybot-deploy"   # paste ~/.ssh/brnzybot_deploy.pub
   # Defaults are fine for the free tier:
   #   region        = "us-central1"   # must be us-central1/us-east1/us-west1
   #   ssh_user      = "brnz"           # this becomes GCE_USER
   #   instance_name = "brnzybot"
   #   machine_type  = "e2-micro"       # free-tier; do not change unless you want billing
   ```

4. **Create the VM:**
   ```bash
   terraform init
   terraform apply        # review the plan, type "yes"
   ```
   When it finishes, note the outputs — especially the **static IP**. That IP is
   your `GCE_HOST`. (You can reprint outputs anytime with `terraform output`.)

The VM's startup script installs Docker and creates the `brnz` user and the
`~/openclaw-data` / `~/openclaw-logs` directories on first boot. Give it a
minute or two to finish bootstrapping before the first deploy.

---

## Part 5 — Add the GitHub deploy secrets

In **your** GitHub repo → **Settings → Secrets and variables → Actions → New
repository secret**, add:

| Secret | Value |
|---|---|
| `GCE_HOST` | The static IP from `terraform output` |
| `GCE_USER` | `brnz` (the `ssh_user` from Part 4) |
| `GCE_SSH_KEY` | The **private** key contents — `cat ~/.ssh/brnzybot_deploy` (include the `BEGIN/END` lines) |

These are what `.github/workflows/deploy.yml` uses to SSH in.

---

## Part 6 — Create the secrets file on the VM

The bot reads its config from `~/brnzybot.env` on the VM. This file lives
**outside** the repo so it survives every `git reset --hard` deploy. The deploy
**fails fast** if it's missing.

SSH in and create it:

```bash
ssh brnz@<GCE_HOST>
nano ~/brnzybot.env
```

Paste this, filling in your real values (template:
[`.env.example`](../.env.example)):

```dotenv
# ── Discord ──────────────────────────────────────────────
DISCORD_BOT_TOKEN=<paste the bot token from Part 1>
HOME_GUILD_ID=<Opera Wipe Society server ID from Part 1>

# Single-guild bot → make slash commands appear INSTANTLY in this server
# instead of waiting up to ~1 hour for Discord's global propagation.
# (See the note below before keeping this on.)
DEV_GUILD_SYNC=true

# ── Warcraft Logs ────────────────────────────────────────
WCL_CLIENT_ID=<from Part 2>
WCL_CLIENT_SECRET=<from Part 2>

# ── Guild defaults ───────────────────────────────────────
DEFAULT_REALM=<your guild's realm, e.g. dreamscythe>
DEFAULT_REGION=us
CURRENT_PHASE=2

# ── AI layer: OFF (deterministic mode — the right call for e2-micro) ──
ENABLE_LLM=false
```

Save (`Ctrl-O`, `Enter`, `Ctrl-X`), then `exit`.

> **About `DEV_GUILD_SYNC=true`:** despite the "dev" name, it's the better
> setting for a bot that lives in **one** server. It syncs slash commands to
> `HOME_GUILD_ID` immediately and clears the global set so commands never appear
> twice. **If you ever add the bot to a second server,** flip it to `false` (or
> remove it) and redeploy — that switches to global sync (commands then take up
> to ~1 hour to appear, but show up everywhere). This logic lives in `bot.py`.

> **`ENABLE_LLM=false` is intentional.** All core commands — `/gearprio`,
> `/gearcheck`, `/strat`, `/abilities`, `/bossguide`, `/simexport` — run fully on
> local data with no AI key and no extra container. Only natural-language chat
> degrades to a "use a command" hint. Leave it off unless you deliberately want
> the conversational layer (that needs a bigger, **billed** VM and an
> `ANTHROPIC_API_KEY` — see [`DEPLOYMENT.md`](DEPLOYMENT.md)).

---

## Part 7 — First deploy

Trigger the deploy workflow. Easiest first run: **GitHub → Actions → "Deploy to
GCE" → Run workflow** (the `workflow_dispatch` button). From then on, **every
push to `master`** auto-deploys.

The workflow SSHes into the VM, clones the repo on first run, `git reset --hard`s
to `master`, copies `~/brnzybot.env` → `.env`, runs `docker compose up --build -d`,
and health-checks `http://localhost:8081/health`. First build takes a few minutes
on the little box.

When the workflow goes green, the bot is **online** — but it can't do gear or
strategy lookups yet, because the databases aren't built. That's Part 8.

---

## Part 8 — Build the item & strategy databases (one time)

The item and strategy DBs are gitignored and **not** in the image, so they must
be built onto the VM's data disk once. The simplest way is to run the build
scripts **inside the already-running container** (it has Python + all deps):

```bash
ssh brnz@<GCE_HOST>
cd ~/brnzybot-git

# Download the item source data and build both DBs into the data volume:
docker compose exec brnzybot sh -c '
  curl -sL https://raw.githubusercontent.com/wowsims/tbc/master/sim/core/items/all_items.go -o /tmp/all_items.go &&
  python3 scripts/import-items.py &&
  python3 build_strategy_db.py
'
```

This writes `tbc_items.db` and `tbc_strategy.db` into `~/openclaw-data` on the
VM (mounted as `~/.openclaw/data` inside the container). `brnzybot.db` (per-server
config) is created automatically on first start.

Restart to be safe, then confirm health:

```bash
docker compose restart brnzybot
curl -sf http://localhost:8081/health && echo " — OK"
exit
```

> `import-items.py` needs outbound internet to fetch `all_items.go`; the VM has
> it. If your GCP network policy blocks egress, build the DBs on your laptop
> instead and `scp` `tbc_items.db` / `tbc_strategy.db` into
> `brnz@<GCE_HOST>:~/openclaw-data/`.

---

## Part 9 — Invite the bot and finish setup in Discord

1. Open the **invite URL** from Part 1 in a browser, choose **Opera Wipe
   Society**, and authorize. The bot should appear **online** and will DM you (the
   server owner) a short welcome with the first steps.
2. In any channel the bot can see, run:
   ```
   /setup realm <your realm slug>     e.g. /setup realm dreamscythe
   /setup phase 2                     match your server's current content phase
   /addchar <character> <spec>        e.g. /addchar Brnz destro
   /listspecs                         see every supported spec
   ```
   `/setup` commands require **Manage Server**.
3. **Verify it works end-to-end:**
   ```
   /gearcheck <character>     full head-to-toe BiS comparison
   /gearprio  <character>     ranked upgrade priority list
   /strat <boss>              boss strategy lookup
   ```

If `/gearcheck` returns real gear, you're fully live. 🎉

Optional admin niceties: `/setup officerole`, `/setup botduellog`,
`/verbosity`, `/response` — see the [README command list](../README.md#commands).

---

## Day-2 operations

**Deploying changes.** Push to `master` → it auto-deploys. Or trigger **Actions →
Deploy to GCE** manually.

**Rolling to a new content phase.** When a phase ships, refresh the item DB and
bump each guild forward (details in [`DEPLOYMENT.md`](DEPLOYMENT.md#rolling-the-bot-to-a-new-content-phase)):
```bash
# on the VM, inside ~/brnzybot-git:
docker compose exec brnzybot sh -c '
  curl -sL https://raw.githubusercontent.com/wowsims/tbc/master/sim/core/items/all_items.go -o /tmp/all_items.go &&
  python3 scripts/import-items.py && python3 scripts/enrich-boss-drops.py'
# then in Discord:
/setup phase 3
```

**Health & logs.**
```bash
ssh brnz@<GCE_HOST>
cd ~/brnzybot-git
curl -sf http://localhost:8081/health      # {"status":"ok"}
docker compose ps                          # container state
docker compose logs -f brnzybot            # live logs
tail -f ~/openclaw-logs/brnzybot.log       # persisted log file
```

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Deploy fails: `~/brnzybot.env is missing` | You skipped Part 6 — create the secrets file on the VM. |
| Bot won't log in / token errors in logs | Wrong `DISCORD_BOT_TOKEN`, or **Message Content Intent** not enabled (Part 1, step 4). |
| Bot is online but **no slash commands** appear | With `DEV_GUILD_SYNC=true`, check `HOME_GUILD_ID` is the correct server ID. Without it (global sync), allow up to ~1 hour, or re-invite ensuring the `applications.commands` scope was granted. |
| Slash commands appear **twice** | Both guild and global scopes are registered — keep exactly one. Set `DEV_GUILD_SYNC=true` for single-guild, then redeploy (`bot.py` clears the other scope). |
| `/gearcheck` says it can't locate gear data | Databases not built — do Part 8. |
| Deploy hangs ~30 min then cancels | `docker build` starved the e2-micro. Add swap (see [`DEPLOYMENT.md`](DEPLOYMENT.md#operating-on-a-free-tier-e2-micro)). |
| Health check fails after deploy | Container crashed on boot — `docker compose logs brnzybot`. |
| `/gearprio` recommends odd/unobtainable gear | Known item-source-data gap; see [`BACKLOG.md`](../BACKLOG.md). Core comparisons are still correct. |

---

## Appendix A — run it on any Docker host (no GCP)

Don't want cloud infra? Any always-on machine with Docker works. You skip Parts
4–8 and instead:

```bash
git clone https://github.com/<your-account>/BrnzyBot.git
cd BrnzyBot
cp .env.example .env          # fill in the same values as Part 6
docker compose up --build -d  # deterministic mode (bot only)

# build the databases into the container's data volume:
docker compose exec brnzybot sh -c '
  curl -sL https://raw.githubusercontent.com/wowsims/tbc/master/sim/core/items/all_items.go -o /tmp/all_items.go &&
  python3 scripts/import-items.py && python3 build_strategy_db.py'
docker compose restart brnzybot
```

Then do Part 1 (Discord bot) and Part 9 (invite + in-Discord setup) exactly as
above. The default compose file bind-mounts `/home/brnz/openclaw-data` and
`/home/brnz/openclaw-logs`; create those dirs or adjust the paths in
`docker-compose.yml` for your host.

---

## Where to go next

- [`DEPLOYMENT.md`](DEPLOYMENT.md) — the operator's runbook (LLM tier, second
  instances, sizing, swap).
- [`README.md`](../README.md) — full command reference and runtime modes.
- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) — how the pieces fit and the exact
  LLM-dependency map.
