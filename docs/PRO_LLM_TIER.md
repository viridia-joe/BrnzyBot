# Pro tier with a local/open LLM — feasibility & plan

*Research date: June 2026. Prices are approximate and move; re-check before committing.*

## TL;DR

- **Goal is feasible; the literal framing is not.** A $10/mo Pro tier that turns on
  the LLM features at a healthy gross margin is very achievable. But the specific
  picture — *each subscriber's box scales up and stands up its own always-on local
  LLM* — is **not** margin-positive: the smallest box that can run a usable LLM
  costs far more than $10/mo, and a CPU box cheap enough is too slow.
- **What works instead:** keep the bot on its cheap box and route Pro guilds' LLM
  calls to a **shared open-model backend** — either a hosted open-source-model API
  (pennies per guild) or **one** self-hosted open LLM (serverless GPU, scale-to-zero)
  amortized across all subscribers. Both leave 90–99% gross margin on $10.
- **The code is ~90% ready.** The bot already speaks an OpenAI-compatible endpoint
  via the LiteLLM proxy, already gates every LLM feature behind `ENABLE_LLM` with
  deterministic fallbacks, and already has a billing cog + per-guild config. The
  feature is mostly *entitlement + billing + backend wiring*, not new infra per guild.

## Why the per-guild always-on box fails the math

A "modest" open model means ~7–8B params (Llama 3.1 8B, Qwen2.5 7B, Gemma 2 9B),
Q4-quantized ≈ 5–6 GB. To serve it interactively you need either a GPU or a lot of
CPU, **always on** if it's dedicated:

| Dedicated always-on box | ~Cost/mo | 8B speed | Verdict for $10/mo |
|---|---|---|---|
| GCP e2-micro (1 vCPU/1 GB) | ~$0 (free tier) | can't load it | ✗ too small |
| GCP e2-standard-2 (2 vCPU/8 GB), CPU infer | ~$49 ($24 spot) | ~3–10 tok/s → a 2048-tok gear note = **4–11 min** | ✗ over budget **and** too slow |
| Small GPU VM (L4/A10), always on | ~$500/mo on-demand, ~$150–290 spot | ~40–80 tok/s (good) | ✗ 15–50× the subscription |

So one dedicated box per $10 subscriber is deeply negative. The fix is to **not**
give each guild its own box.

## Pricing research (June 2026)

**Hosted open-source-model APIs** (you call an OpenAI-compatible endpoint):

| Provider / model | $/M input | $/M output |
|---|---|---|
| Groq — Llama 3.1 8B | $0.05 | $0.08 |
| DeepInfra — Llama 3.1 8B | ~$0.06 (blended) | ~$0.06 |
| Together — Llama 3.1 8B | ~$0.18 | ~$0.18 |
| Groq — Llama 3.3 **70B** | $0.59 | $0.79 |

**Self-hosted (you run the model):**

| Option | ~Cost | Notes |
|---|---|---|
| Serverless GPU A10G (Modal) | ~$1.10/hr, **billed per-second, $0 idle** | ~$0.0003/s; scale-to-zero |
| Serverless GPU A10/L4 (RunPod) | ~$0.69–0.84/hr per-second | lower rate, some idle |
| Always-on GPU VM (L4/A10) | ~$150–290/mo (spot) | only sane at high utilization |
| GCP e2-standard-2 CPU | ~$49/mo ($24 spot) | too slow for big outputs |
| **Oracle Cloud Always-Free Ampere A1** (4 OCPU/24 GB ARM) | **$0, indefinitely** | CPU-only ~5–10 tok/s; fine for short outputs, slow for 2K-tok gear notes |

Sources: [DeepInfra](https://deepinfra.com/pricing), [Together](https://www.together.ai/models/llama-3-1),
[Groq](https://groq.com/pricing), [Modal](https://modal.com/pricing), [RunPod](https://www.runpod.io/pricing),
[GCP e2-standard-2](https://www.economize.cloud/resources/gcp/pricing/compute-engine/e2-standard-2/),
[Oracle Always Free](https://www.oracle.com/cloud/free/).

## Workload & per-guild cost estimate

LLM-touching surfaces and their output budgets (from the code): `/gearprio`
annotation (≤2048 tok), `/strategy`, `/bossguide` (≤1600 + vision), `/rotationcheck`
coach (300), NL `classifier`/`triage` (256). Call it **~1–4 K tokens per LLM
command**. A raid guild realistically fires maybe **100–500 LLM commands/month**
→ ~0.5–2 M tokens/guild/month (generous).

**Cost per Pro guild per month:**

| Backend | ~Cost/guild/mo | Gross margin on $10 |
|---|---|---|
| Groq/DeepInfra 8B | **$0.03–0.12** | ~99% |
| Together 8B | $0.10–0.40 | ~96–99% |
| Groq 70B (higher quality) | $0.40–1.60 | ~84–96% |
| Serverless GPU (self-host 8B), low volume | ~$1–4 (+cold starts) | ~60–90% |

Even the most expensive sane option clears margin. The runaway risk isn't unit
cost — it's an unbounded user hammering it (mitigation below).

## Architecture options

**A. Hosted open-model API behind LiteLLM (recommended v1).** Point
`LITELLM_BASE_URL` model routes at Groq/DeepInfra. Pro guild → `ENABLE_LLM` path
on, calls go out, ~$0.10/guild. Near-zero ops, profitable from subscriber #1.
Trade-off: not self-hosted (data leaves to the inference vendor; it's still an
open-weights model, just someone else's GPU).

**B. One shared self-hosted open LLM (the "local" path).** Stand up a single
vLLM/Ollama serving an 8B (or 70B) for **all** Pro subscribers, fronted by the
existing LiteLLM proxy. Use a **serverless GPU (Modal/RunPod, scale-to-zero)** so
you pay per inference-second, not for idle. Margin-positive at any scale; full
control and data stays in your stack. Trade-off: cold-start latency (~10–30 s to
load) unless kept warm; more ops than A.

**C. Dedicated GPU box, shared across subscribers.** Once continuous utilization
is high enough that a reserved spot GPU (~$150–290/mo) beats per-second serverless
— i.e. ~30–60+ active Pro guilds — move B onto a reserved box. Pure scale economics.

**Not recommended:** a box per guild (the original framing) — negative margin.

## How it maps onto what's already built (minimal changes)

| Need | Already there | New work |
|---|---|---|
| Talk to any OpenAI-compatible LLM | `core/llm.py` + `config.LITELLM_BASE_URL` (LiteLLM proxy) | point a route at the open-model backend |
| Turn features on/off with safe fallback | `config.ENABLE_LLM` gates every LLM site | make it **per-guild** (see below) |
| Per-guild settings | `guild_config` table, `/setup`, billing cog | add a `pro` entitlement column + check |
| Usage limits (abuse/cost cap) | `check_rate_limit` / `log_usage` already exist | add a Pro token/£ budget cap |
| Subscriptions | billing cog scaffold | Stripe (or Discord monetization) webhook → set `pro` |

**Per-guild vs instance-level gating.** Today `ENABLE_LLM` is a *global* (per-process)
flag. Two clean paths:
- **Instance-level (simplest, matches current deployment):** "Pro" = a separate
  instance with `ENABLE_LLM=true` pointed at the backend; free guilds run a
  deterministic instance. Zero code change.
- **Per-guild (true SaaS):** add `guild_config.pro` and have the LLM handlers
  check `ENABLE_LLM and is_pro(guild_id)`. One small helper, threaded like the
  existing phase/arena settings. Needed only if one instance serves mixed
  free/paid guilds.

## Build plan (phased)

**Phase 1 — Pro entitlement + hosted backend (1–2 days).**
1. `guild_config.pro` (+ migration) and `is_pro(guild_id)`; gate LLM sites on
   `config.ENABLE_LLM and is_pro(guild_id)` (deterministic fallback already exists).
2. LiteLLM config: add an open-model route (Groq/DeepInfra) for the bot's model
   aliases; keep Claude as an optional premium route.
3. Per-guild **monthly token/cost cap** via `log_usage` (e.g. hard stop + friendly
   message at N calls/month) so one guild can't run up the bill.
4. Billing: wire Stripe Checkout (or Discord's built-in monetization) → webhook
   sets/clears `pro`. Grace handling on lapse → silently revert to deterministic.

**Phase 2 — Self-hosted "local" backend (optional, 2–4 days).**
5. Containerize vLLM/Ollama serving the chosen open model; deploy to serverless
   GPU (Modal/RunPod) with scale-to-zero; expose an OpenAI-compatible URL.
6. Repoint the LiteLLM route from the hosted API to the self-hosted endpoint. No
   bot code change. Add a warm-ping if cold-start latency hurts UX.

**Phase 3 — scale economics.** Move to a reserved spot GPU when utilization makes
it cheaper than per-second serverless; add basic per-backend cost monitoring.

## Risks & mitigations

- **Runaway token cost** → per-guild monthly caps (reuse `log_usage`/`check_rate_limit`);
  alert + auto-throttle. This is the only real cost risk.
- **Latency** → 8B on a GPU is ~1–3 s for short outputs; the heavy 2048-tok gear
  note is ~25–50 s. Keep the deterministic skeleton instant and stream/append the
  LLM annotation; on serverless, keep-warm or accept first-call cold start.
- **Quality** → an 8B open model is fine for coaching/annotation tone; if it reads
  weak, bump to 70B (still ~$0.4–1.6/guild) or keep Claude as a premium toggle.
- **Billing/tax/refunds** → use Stripe or Discord monetization; don't hand-roll.
- **ToS/abuse & data** → hosted APIs see prompt content (gear/log data, low
  sensitivity); self-host (Phase 2) if that matters. Add basic prompt-injection
  guarding on any user free-text that reaches the model.

## Feasibility verdict

- **Technical: HIGH.** The LiteLLM abstraction, the `ENABLE_LLM` gating with
  deterministic fallbacks, per-guild config, and the billing scaffold mean this is
  mostly wiring (entitlement + caps + Stripe + a backend route), not a rebuild.
- **Commercial: positive, with the right architecture.** At ~$0.10–1.60 backend
  cost per Pro guild, $10/mo is **80–99% gross margin** using a shared/hosted
  open model. Fixed costs are near-zero with a hosted API (profitable from the
  first subscriber) or ~$150–300/mo if you self-host a baseline GPU (break-even
  ~30–60 subscribers). The binding constraint is **demand** (niche: WoW-Classic
  raid teams), not unit economics.
- **One-line answer:** Don't scale a box per subscriber. Flip a per-guild Pro flag
  that routes LLM calls to a shared open model (hosted first, self-hosted later),
  cap usage, and you net well over half of every $10 — likely ~$9.
