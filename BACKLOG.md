# Backlog

## Recently Shipped
- `/audit` Preparation cut — enchants, gems, meta, consumes, iLvl per raider
- `/audit` Execution section — rotation anomaly check wired to cast data
- Offline fixture harness — synthetic WCL logs, item-DB fixture, CI audit
- WCL client unified — `gear_cache` uses `wcl_client` (retry/breaker/fixtures)
- Healer analysis in `/gearcheck` — throughput + regen metrics, pass/fail thresholds
- `/srprio <character> <raid>` — top-5 SR picks by EP for a named raid instance
- Gems & enchants summary in `/gearcheck` — empty sockets, missing enchants, meta check
- Spec-search in `/gearcheck` — walks recent logs to find the right spec when explicit
- Rotation profiles — 20 specs (all DPS, all classes)
- Rotation baselines pipeline — `scripts/build_baselines.py` pulls top-N Anniversary parses
- `🥇` emoji fix — Phase 1 BiS items now correctly marked vs current-phase BiS
- `/gearprio` double-subtraction fix + BiS-equivalence test harness
- `/srprio` — fully working after source_type filter fix (25-man Raid/10-man Raid)
- Item DB source data — 4,342/4,389 items enriched; World Boss=16, Arena=718, raids correct
- Fight diagram framework — per-boss PNG lookup with authoring tool
- Dead code removed — `core/gearprio.py`, `core/compute-upgrades.py`, `core/triage.py` body
- Heartbeat mojibake fix — lore/tips/jokes UTF-8 repaired
- Heartbeat content accuracy — raid tips (56/76 had hallucinated mechanics), lore (14 fixes), jokes (70 quality rewrites), CN-meme spammacros (17 rewritten) all deep-researched & corrected
- Per-fight spec detection — `/audit`, `/rotationcheck`, `/addchar` detect spec from the log's stat block (handles dual-spec / spec-switchers); tank-vs-healer ordering fixed
- Tank rotation profiles — prot warrior/paladin, bear druid (threat + wrong-stance/form flags)
- `/raidaudit` — whole-night consumable matrix (food/oil/flask/potion per boss, role-aware grading, creature-type waste flags)
- Deploy changelog — posts New Features/Improvements/Bug Fixes on redeploy instead of lore
- 6-tier gear markers (🥇🔥🥈↔️❄️💩) by EP gap; unscored-item (proc trinket) backlog
- Boss content store unified — SSC/TK wired into `/strat` + `/bossguide` (other session)

---

## 🗺️ Phase 2–5 readiness — see [`docs/PHASE_READINESS.md`](docs/PHASE_READINESS.md)

**Priority:** High · **Effort:** High (content is the long pole)

Plan for content-phase rollovers: a **realm + date driven** phase model
(auto-advances realm-wide, removes the per-guild `/setup phase` burden; fixes the
Anniversary 4-phase vs. original 5-phase mismatch and the Zul'Aman item-ceiling
trap), consolidating the three boss-content stores into one `content_phase`-tagged
schema, and a sourced anti-hallucination research workstream for the SSC→Sunwell
strategies (reusing the proven verify-raid-tips deep-research loop). Source-data
enrichment (former keystone) has shipped — §4 now just retires the redundant
world-boss/arena stopgaps. Sequenced to land before Anniversary P3 (summer 2026).

---

## Reaction Feedback Harvesting (👍 / 👎 on bot responses)

**Priority:** Medium · **Effort:** Medium

`core/feedback.py` exists but is **unwired** — no `on_raw_reaction_add` listener anywhere. Work is connecting it, not building from scratch.

Remaining:
- Reaction listener cog mapping 👎/❌ → negative, 👍/🎯 → positive on bot's own messages
- Log response text at post-time (keyed by message_id) so the harvester has the actual answer
- `tools/feedback_cli.py` offline digest, or owner-only `/feedback review`

---

## Gear Correctness — Externally-Grounded BiS Validation

**Priority:** High · **Effort:** High (content is the long pole)

`tests/test_bis_equivalence.py` (shipped) pins gearprio/gearcheck against the optimizer's own BiS (internal consistency). Still open: compare `solve_bis` to **human-verified curated BiS lists** (`data/bis/<spec>_p<N>.json`) to catch bad weights or bad item data that internal consistency can't detect.

---

## Weapon Slot Display in `/gearprio`

**Priority:** Low · **Effort:** Low

The double-subtraction fix made weapon upgrades surface with correct EP, but the "from" item renders as `(empty)` for staves/2H because WCL slot names (`Main Hand`) don't match DB slot names (`Two-Hand`). Cosmetic only — the EP values are right. Fix: share `/srprio`'s `_canon_slot` normalizer.

---

## Raid Audit — Execution Section

**Priority:** High · **Effort:** Medium

Preparation audit is shipped. Execution phase wired (cast analysis from rotation handler). Still open: parse % from `get_rankings`, movement/uptime metrics, more spec profiles beyond casters.

---


## Food Buff Aura Names — verify the long tail

**Priority:** Low · **Effort:** Low

Most TBC (Outland) food shows the generic **"Well Fed"** aura in WCL; some legacy Vanilla cooking foods still show their original **stat-named buffs**. `profiles.FOOD_AURAS` now matches the full set. **Confirmed against live Dreamscythe logs:** `Well Fed`, `Enlightened` (Skullfish Soup — +20 spell crit/+20 spirit; a crit/longevity pick, slight throughput loss vs +spell-damage food but legit). **From research, not yet seen in a live log — verify the exact aura string before fully trusting:** `Mana Regeneration` (Smoked Sagefish/Nightfin Soup), `Health Regeneration` (Tender Wolf Steak), `Increased Intellect` (Runn Tum Tuber Surprise), `Increased Stamina/Agility/Strength/Spirit` (legacy foods), `Electrified` (Stormchops proc — gives no stats, recognized but not a real food signal). When one of these shows up in a real audit, confirm the literal `name` field matches and tighten if needed.

---

## Enchant Database

**Priority:** Low · **Effort:** Medium

Tank defense calculation uses a hardcoded enchant ID → defense rating map. Build a proper `enchant_id → stats` SQLite table sourced from WowSims/Wowhead. Unblocks more accurate tank EP and opens enchant recommendations.

---

## Set Bonus Awareness in BiS

**Priority:** Low · **Effort:** High

BiS solver treats set pieces independently; it doesn't account for activating or breaking set bonuses. Good enough for Phase 1/2. Revisit if set bonus value becomes dominant in later phases (T6 4pc etc.).

---

## Relic EP Overrides

**Priority:** Low · **Effort:** Low

Totems, Idols, Librams show "proc-based, not EP-rated." Could get spec-specific override EP values like trinkets. Rarely the bottleneck.

---

## Fight Diagram Content

**Priority:** Medium · **Effort:** Medium (asset authoring)

Framework shipped. Remaining: author real minimap backgrounds + per-boss JSON specs, commit rendered PNGs for P1–P2. Code is done; this is content work.

---

## Scrub Em-Dashes from Boss Strat Prose

**Priority:** Low · **Effort:** Low

`data/strategy/*.json` is **done** (scrubbed to plain ASCII and now covered by the `test_json_validity` unicode guard). Remaining: `data/boss_strats.json` (~58 em-dashes) if it's still user-facing. Don't touch Python module docstrings (house convention per CLAUDE.md).
