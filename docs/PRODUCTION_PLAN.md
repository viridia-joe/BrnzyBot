# BrnzyBot — Path to Production

Assessment date: 2026-06-08. Based on a full-codebase review (deploy/infra, feature
surface, monetization, code quality). This is the punch list to go from "running
on my VM" to "confidently inviting strangers."

## TL;DR — where we are

The bot is **functionally complete and already deployed**. 12 cogs, ~45 user-facing
commands, all working with `ENABLE_LLM=false` (zero model cost). Auto-deploys on push
to master. The deterministic core (gear optimizer, rotation check, audit, srprio) is
well-tested and correct after the recent bug-fix pass.

**It is safe to beta test today** — no cost risk (LLM off, Stripe not wired, 20/day
free cap per guild). The gap is not features; it's **operational hardening**: failure
visibility, data durability, and a few rough edges a stranger would hit.

Production-readiness: **7/10**. The three things below move it to 9.

---

## P0 — DONE (2026-06-10, all shipped + verified in prod)

All five completed before beta. Health endpoint verified returning
`ready: true, loaded_cogs: 12`; backup cron installed on the VM (daily 04:00).

1. ✅ **Cog-load resilience + real health check.** Each cog loads independently;
   one bad import no longer kills boot. `/health` reports ready state + cog counts
   and returns 503 when degraded, so the deploy gate is meaningful. (`bot.py`)
2. ✅ **Database backup.** `scripts/backup_db.sh` does a daily online `sqlite3.backup()`
   of `brnzybot.db` (14 local snapshots, optional GCS push), installed via cron on the VM.
3. ✅ **SQLite busy timeout.** `PRAGMA busy_timeout=5000` in `_conn()`.
4. ✅ **Timeout fallback messages.** gear/rotation/audit send a best-effort ephemeral
   "that took too long" instead of leaving a stuck spinner.
5. ✅ **URL validation.** `/audit` and `/rotationcheck` validate the report link up
   front and reply instantly on a typo.

## P1 — Do during beta, before any public launch (1–2 days)

6. **Deploy = `git reset --hard origin/master`** (`deploy.yml`). One bad commit is live
   instantly with no rollback. Lowest-effort fix: keep deploying master but add a
   post-deploy smoke step that curls `/health` and, if it fails, `git reset --hard` to
   the previous SHA and redeploys. Real fix: tag releases, deploy tags.

7. **WCL staleness disclosure.** `gear_cache` silently serves cached gear when WCL is
   down. Add an age check; if the snapshot is >24h old, append "_(gear from cache,
   WCL was unreachable — may be stale)_" to the output. Honesty > silent wrong data.

8. ✅ **Log rotation.** Done alongside P0 — `RotatingFileHandler` 10MB × 5 in `bot.py`.

9. **A `/help` command.** There is none today — discovery relies on Discord's slash
   autocomplete and the onboarding DM. A single `/help` that lists the command groups
   (gear, raid, strategy, fun) is the #1 thing a confused tester wants. High UX
   leverage, low effort.

10. **Integration test for one full command path.** Today every test is unit-level;
    no test exercises a cog handler end-to-end, so a broken `@app_commands` signature
    or a bad defer/followup ships green. Add one (mock the interaction, call
    `slash_gearcheck`, assert it sends a message). Template for the rest.

## P2 — Before monetization / scale (when it's earned)

11. **Wire Stripe.** Code is complete (`webhook_server.py`, `cogs/billing.py`) but
    `STRIPE_PAYMENT_LINK` and `STRIPE_WEBHOOK_SECRET` are unset, so `/subscribe` says
    "not enabled yet." Deploy the webhook sidecar + set the secrets when there's demand.
    **Define pricing first** — there's no number anywhere yet.

12. **Turn on LLM for Pro guilds.** Currently `ENABLE_LLM=false` globally. The
    entitlement gate (`llm_enabled` = ENABLE_LLM AND is_pro AND under monthly cap) is
    built and tested; the 3000-call/guild/month cap bounds cost to ~$4.50/guild. Flip
    it on only once Stripe is live so "Pro" means something.

13. **Multi-instance WCL rate limiting.** If you ever run a second instance, they share
    one WCL client-id and burn the rate limit together. Only matters at scale; documented
    in DEPLOYMENT.md.

## What's explicitly fine to ignore

- **scipy/numpy on 1GB:** the MIP solver loads fine; no action.
- **`restart: unless-stopped`** is set, so a crash auto-recovers — the OOM/crash story
  is acceptable for beta.
- **Heartbeat "haiku" key:** the data file uses `spammacros` and so does the code; the
  only mismatch is a stale docstring. Cosmetic, not a bug.
- **NL chat in deterministic mode:** falls back to "use a command." Fine — just steer
  testers toward slash commands (the recruitment post does this).
- **SQL/path/shell injection:** none found. Queries are parameterized, paths are
  `os.path.join` on controlled dirs.

## Suggested sequence

Day 1: P0 items 1–5 (half a day of focused work), deploy, smoke-test yourself.
Then: invite beta testers (post below). Collect real failure reports.
Week 1–2: P1 items as the beta surfaces what actually matters.
Later: P2 only if beta demand justifies turning on paid LLM features.
