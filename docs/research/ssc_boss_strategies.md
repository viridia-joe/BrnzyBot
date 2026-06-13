# Serpentshrine Cavern — verified boss-strategy research (pilot)

**Status:** research output for review · generated 2026-06-13 · raid content_phase **2**

This is the **pilot** for the [`PHASE_READINESS.md`](../PHASE_READINESS.md) §3
research workstream — replacing hand-authored/AI strat content with sourced,
cross-verified content before scaling to the other five raids. It is **not yet
wired into `/strat` or `/bossguide`** (that's the §2 schema consolidation, pending
sign-off on this quality bar).

## How this was produced + confidence model

- Five parallel research agents (one per boss / boss-pair), anchored on **Wowhead
  TBC, Icy-Veins TBC, Warcraft Wiki**, with fan tactics sites as corroboration only.
- **Every non-obvious mechanic required ≥2 independent sources.** Disagreements and
  unconfirmed numbers are flagged **UNVERIFIED**, not guessed.
- **Hydross got three independent passes** that fully agree — highest confidence.
- **Sourcing caveat (important):** direct `WebFetch` returned **HTTP 403 on every
  anchor site** (Wowhead, Icy-Veins, Warcraft Wiki, Wowpedia) in this environment.
  All claims rest on **search-result snippets cross-checked across sources**, not
  full-page reads. Net effect:
  - **High confidence:** mechanic *existence*, *handling*, *roles*, *kill orders*,
    *phase thresholds*, *add compositions* — the qualitative content a strat guide
    actually needs.
  - **Low confidence:** exact *numbers* (damage values, timers, HP, resist targets).
    These are flagged and should **not** ship in user-facing text without a
    working-fetch verification pass — and arguably shouldn't be quoted at all
    (raiders need "spread for Static Charge," not "1,619 nature dmg").

**The methodology caught real hallucinations** (the whole point): Hydross has *no*
transition-count enrage and the adds have *no* "Water Bolt/Poison Spit" casts;
Leotheras's demon tank needs **Fire** resistance, **not** shadow; Morogrim's Watery
Grave victims do **not** drown / don't need freeing. All corrected below.

---

## 1. Hydross the Unstable  ·  *triple-verified*

- **Aliases:** Hydross. **Type:** dual-element resistance tank-swap (two tanks).
- **Summary:** A water elemental with two positional forms. **In the water = Pure
  form = Frost** (deals/immune to Frost); **dragged onto land = Corrupted form =
  Nature** (deals/immune to Nature). Each form applies a raid-wide stacking Mark
  amplifying that school; the raid lets it build to ~4 stacks then drags him across
  the boundary to swap, which clears the Mark but spawns 4 same-element-immune adds.
  Rhythm of stack → transition → AoE adds, beat the 10-min enrage.
- **Mechanics:**
  - **Mark of Hydross** (Frost form) / **Mark of Corruption** (Nature form) —
    raid-wide, stack to 6, amplify that school's damage (10/25/50/100/250/500%),
    applied ~every 15s. Transition at ~4 stacks (+100%) before it's unhealable.
  - **Transition adds** — crossing INTO water → 4 **Pure Spawn** (Frost, immune to
    Frost); onto land → 4 **Tainted Spawn** (Nature, immune to Nature; CC-able).
    Kill with the opposite school.
  - **Water Tomb** (Frost) — random-target AoE stun, ~8 yd; spread.
  - **Vile Sludge** (Nature) — random-target DoT, −50% damage/healing done; afflicted
    spreads out.
  - **Form change resets all threat** → all DPS STOP at each transition or an
    accidental re-cross spawns a second add wave (signature wipe).
  - **Hard enrage ~10 min.**
- **Roles:** **Tanks** — one Frost-resist set (water), one Nature-resist set (land);
  resist cap = 365 (=5×lvl73); Warrior Iceguard/Wildguard sets are the base, topped
  by Pally aura / Shaman totem. **Healers** — stack-driven; the transition call is
  effectively healer-driven; spot-heal Tomb/Sludge targets. **DPS** — swap to the
  non-immune school; burn boss, then AoE the 4 adds; hard-stop before transitions.
- **Killers:** marks reaching +250/500%; accidental extra transition (second add
  wave); wrong-resist tank active; clumping into Water Tomb; enrage.
- **Prep:** FR + NR tank sets; add tank (mixed resist, low/no resist OK); transition
  caller at ~4 stacks; AoE for the add packs.
- **Sources:** icy-veins.com/tbc-classic/hydross-the-unstable-guide-strategy-abilities-loot ·
  warcrafttavern.com/tbc/guides/hydross-the-unstable/ ·
  warcraft.wiki.gg/wiki/Hydross_the_Unstable · wowpedia.fandom.com/wiki/Hydross_the_Unstable ·
  warcraft.wiki.gg/wiki/Pure_Spawn_of_Hydross · /wiki/Tainted_Spawn_of_Hydross · royalgiraffe.github.io/hydross

---

## 2. The Lurker Below

- **Aliases:** Lurker, "Fishy." **Type:** flooded-platform single-target with a
  recurring submerge/add intermission (positioning + add control, not a DPS race).
- **Summary:** **Fished up** — a designated player with **300 fishing** casts into
  the Strange Pool to surface and pull him (clear surrounding trash first). ~120s
  active phase: MT holds him center while the raid dodges the rotating **Spout**
  (jump into the water to break LoS) and spreads for **Geyser**. He then **submerges
  ~60s**, spawning 9 adds; re-emerges and repeats.
- **Mechanics:**
  - **Spout** — rotating water-beam knockback; jump into the surrounding water to
    avoid (don't spam-jump).
  - **Geyser** — random-target AoE knockback (~10 yd); spread, especially melee.
  - **Water Bolt** — cast **only if no one is in melee range** (near one-shot); always
    keep a melee/tank in range so it never fires.
  - **Submerge adds (9 total):** **6 Coilfang Ambushers** (ranged, 2 on each of 3
    outer platforms) + **3 Coilfang Guardians** (melee cleave, main platform). Kill
    Guardians first. Ambushers **evade if targeted across platforms** — assigned
    players must physically be on the Ambusher's platform or the boss can despawn/reset.
- **Roles:** **Tanks** — MT center-in-melee always (prevents Water Bolt); OT gathers
  + stuns the 3 Guardians. **Healers** — heal on the platform of who you're healing
  (cross-platform healing triggers the Ambusher evade bug). **DPS** — assigned ranged
  per outer platform for Ambushers; melee on Guardians; spread for Geyser.
- **Killers:** Spout knockback off platform / death by spam-jumping; Geyser on a
  clump; boss un-meleed → Water Bolt; leftover adds at re-emerge; Ambusher evade reset.
- **Prep:** clear/"boil" surrounding trash; 300-fishing puller; ranged+healer per
  outer platform; melee+tanks center.
- **Sources:** icy-veins.com/tbc-classic/the-lurker-below-guide-strategy-abilities-loot ·
  wowpedia.fandom.com/wiki/The_Lurker_Below · wowpedia.fandom.com/wiki/Coilfang_Ambusher ·
  wowhead.com/tbc/npc=21217/the-lurker-below (snippet)

---

## 3. Leotheras the Blind

- **Aliases:** Leo. **Type:** two-personality tank-swap (melee Humanoid ↔ ranged
  Demon) with a per-player Inner Demon, ending in a dual-form split.
- **Summary:** Alternates ~45–60s between **Humanoid** (Whirlwinds, resets threat)
  and **Demon** (Chaos Blast — **fire**, tanked at range by a FR Warlock). In Demon
  phase he casts **Insidious Whisper** on up to 5 players, each spawning an **Inner
  Demon** only that player can see/kill within ~30s or be permanently mind-controlled.
  At **15%** the Demon splits off as its own 100%-HP mob while Humanoid keeps its HP;
  both must die together.
- **Mechanics:**
  - **Whirlwind** (Humanoid) — heavy physical + non-dispellable Rend; **not tankable,
    drops all threat when it ends**. Raid spreads/runs; DPS wait for threat after.
    (Rend removable by Limited Invuln Potion / Divine Shield / BoP / Ice Block.)
  - **Chaos Blast** (Demon) — **FIRE** damage, **stacking** fire-taken debuff → ranged
    **Fire-Resistance** tank (Warlock; Demonic Resilience −15% fire). *Not shadow.*
  - **Insidious Whisper / Inner Demon** — up to 5 players, solo-kill-only, ~30s or
    permanent MC. Whispered players instantly switch to their own demon.
  - **15% split** — Demon → separate 100% mob; kill both simultaneously.
- **Roles:** **Tanks** — plate MT on Humanoid (re-threat after every Whirlwind); FR
  Warlock on Demon at range. **Healers** — heavy in Humanoid (Whirlwind/Rend); focus
  the Warlock hard in Demon (Chaos Blast stacks). **DPS** — wait for threat post-WW;
  kill your own Inner Demon on sight; manage the split.
- **Killers:** too many caught by Whirlwind; DPS attacking before re-threat; Inner
  Demons not killed (MC snowball); FR tank undergeared; botched 15% split.
- **Prep:** **Fire** resist for the Warlock demon-tank (+ FR totem/aura); Inner Demon
  discipline drilled; anti-Rend cooldowns assigned.
- **Sources:** icy-veins.com/tbc-classic/leotheras-the-blind-guide-strategy-abilities-loot ·
  warcrafttavern.com/tbc/guides/leotheras-the-blind/ · wowpedia.fandom.com/wiki/Leotheras_the_Blind ·
  warcraft.wiki.gg/wiki/Leotheras_the_Blind · bittsguides.com/fire-resistance-for-leotheras-the-blind/

---

## 4. Fathom-Lord Karathress

- **Aliases:** FLK, Karathress. **Type:** council (boss + 3 advisors); set kill order.
- **Summary:** Four simultaneous targets — Karathress + Fathom-Guards **Tidalvess**
  (shaman), **Sharkkis** (hunter+pet), **Caribdis** (caster/healer). Each advisor's
  death grants Karathress that advisor's signature ability, so the fight gets *more*
  dangerous on the boss as adds fall. Kill order **Tidalvess → Sharkkis → Caribdis →
  Karathress**; do not push the boss below 75% with advisors alive.
- **Mechanics:**
  - **Karathress: Cataclysmic Bolt** (~50% max HP to a random mana user — heal through),
    **Sear Nova** (melee-range AoE), **Blessing of the Tides** (<75% HP → buff per
    living advisor — the reason advisors die first).
  - **Tidalvess:** Spitfire Totem (kill on sight), Poison Cleansing / Earthbind totems,
    Frost Shock + Windfury on his tank.
  - **Sharkkis:** Leeching Throw, Multi-Toss (up to 3), The Beast Within (enrage),
    summons a pet to tank.
  - **Caribdis:** Healing Wave (**must be interrupted** — ignores LoS/range), Water Bolt
    Volley (AoE), Tidal Surge (~10 yd freeze), a roaming Cyclone.
- **Roles:** **Tanks** — 4 (one each; Caribdis tanked in a corner away from raid; pick
  up Sharkkis's pet). **Healers** — heavy through Cataclysmic Bolt + Caribdis AoE.
  **DPS** — kill order above; instant swap to Spitfire Totem; **dedicated interrupt
  rotation on Caribdis** the whole time she's up.
- **Killers:** ignoring Spitfire Totem; failing to interrupt Caribdis; pushing boss
  <75% with advisors up; Cataclysmic Bolt on an un-topped target.
- **Prep:** 4 tanks; interrupt team on Caribdis; instant Spitfire kill; dispellers.
- **Sources:** icy-veins.com/tbc-classic/fathom-lord-karathress-guide-strategy-abilities-loot ·
  warcrafttavern.com/tbc/guides/fathom-lord-karathress/ · warcraft.wiki.gg/wiki/Fathom-Guard_Tidalvess ·
  /Fathom-Guard_Sharkkis · /Fathom-Guard_Caribdis · wowhead.com/tbc/npc=21214/fathom-lord-karathress

---

## 5. Morogrim Tidewalker

- **Aliases:** Morogrim, Tidewalker. **Type:** single-boss tank-and-spank + recurring
  murloc-add waves + forced teleport; globule phase at 25%.
- **Summary:** Largely an AoE/add-control check. **Earthquake** periodically deals
  raid AoE and summons **two packs of 6 murlocs** (one per entrance) that off-tanks
  gather for cleave; **Watery Grave** teleports 4 random players to center and bursts
  them (they do **NOT** drown — just need healing). Boss faces a wall to keep the
  raid out of the **Tidal Wave** frontal cone. Below **25%** he swaps Watery Grave for
  **Water Globules** that fixate and chase players.
- **Mechanics:**
  - **Watery Grave** — teleports 4 players to the waterfall, brief stun + bubble burst
    (~5–6k Frost); dedicated healing, **no freeing/drowning**.
  - **Earthquake** — ~50 yd raid AoE + summons 2×6 Tidewalker Lurker murlocs.
  - **Tidal Wave** — frontal-cone Frost + attack-speed-slow debuff; face boss at a wall.
  - **Summon Water Globule** (≤25%) — replaces Watery Grave; globules fixate/chase.
- **Roles:** **Tanks** — MT holds boss facing a wall; **2 off-tanks** grab the murloc
  packs each Earthquake. **Healers** — 1–2 dedicated to Watery Grave targets; hold raid
  healing until murlocs are picked up (or you pull aggro and die). **DPS** — AoE murlocs
  fast; in P2 handle fixating globules.
- **Killers:** healing the raid before murlocs are tanked (healer pulls aggro);
  neglecting Watery Grave targets; standing in the Tidal Wave cone; murloc waves
  outpacing AoE.
- **Prep:** MT + 2 murloc OTs; 1–2 healers on Watery Grave; AoE DPS assigned; boss
  pre-faced at a wall.
- **Sources:** icy-veins.com/tbc-classic/morogrim-tidewalker-guide-strategy-abilities-loot ·
  warcrafttavern.com/tbc/guides/morogrim-tidewalker/ · wowhead.com/tbc/spell=38025/watery-grave ·
  wowpedia.fandom.com/wiki/Morogrim_Tidewalker

---

## 6. Lady Vashj  ·  *SSC end boss*

- **Aliases:** Vashj, LV. **Type:** 3-phase — tank-and-spank bookends (P1/P3) around a
  tainted-core relay / add-control middle (P2).
- **Summary:** **P1 → 70%:** tank-and-spank, dodge her abilities. **At 70%** she
  shields herself (invulnerable) at center → **P2:** kill **Tainted Elementals** for
  **Tainted Cores**, which **root the carrier** — so **throw** them down a relay chain
  to players at the **four Shield Generators**; each generator disabled removes **5%**
  HP. Meanwhile kite Striders, tank Elites, and kill Enchanted Elementals before they
  buff her. All four generators down (~50%) → **P3:** like P1 but adds continue and
  **Toxic Spore Bats** drop persistent poison — a DPS/space race.
- **Mechanics (by phase):**
  - **P1/P3:** Shock Blast (target nuke + 5s stun), Static Charge (random-target,
    spread — ~10 yd/2s/20s), Entangle (15 yd root), Multi-Shot (up to 5).
  - **P2:** **Tainted Core** (roots carrier; ~1-min timer; relay by throwing, never run
    solo); **Tainted Elemental** (drops cores); **Enchanted Elemental** (low HP, runs at
    Vashj; reaching her = **+5% stacking** damage buff → ranged kill on sight);
    **Coilfang Strider** (un-tankable, ~8 yd AoE **fear** + speed buff → ranged/DoT kite);
    **Coilfang Elite** (one-shots cloth → off-tanked).
  - **P3:** P1 kit + **Toxic Spore Bats** dropping persistent, accumulating poison clouds.
- **Roles:** **Tanks** — MT on Vashj (eats Shock Blast stun) P1/P3; OT on Elites P2;
  nobody tanks Striders. **Healers** — tank-weighted P1/P3; raid-spread P2. **DPS** —
  melee→Elites, ranged→Enchanted Elementals (priority) + Strider kite + Tainted
  Elementals. **Core runners (dedicated P2 role)** — mobile players relay cores by
  throwing to a camper at each of the 4 generators; a shot-caller calls handoffs.
- **Killers:** **#1 = Tainted Core mismanagement** (timer expiry / solo-run / fumbled
  throws); Enchanted Elementals reaching Vashj (unhealable P3); Striders feared into
  the raid; loose Elite; P3 poison floor; Static Charge clumping.
- **Prep:** assign a camper per generator + plan the throw chain + a shot-caller; split
  ranged into quadrants for Elemental/Strider lanes; melee+OT on Elites; fear-break
  utility (Tremor Totem / Fear Ward / trinkets); 5–7 healers.
- **Sources:** icy-veins.com/tbc-classic/lady-vashj-guide-strategy-abilities-loot ·
  warcrafttavern.com/tbc/guides/lady-vashj/ · wowpedia.fandom.com/wiki/Lady_Vashj_(tactics) ·
  warcraft.wiki.gg/wiki/Lady_Vashj_(tactics)

---

## Master UNVERIFIED list (needs a working-fetch numbers pass; do NOT publish as exact)

- **Hydross:** Water Tomb / Vile Sludge exact damage+cadence (TBC vs Classic re-tune split);
  exact transition stack count (3 vs 4 — rule "transition before +250%" is safe); add HP;
  specific resist amounts (365 cap is verified, "how much you need" varies).
- **Lurker:** Geyser damage/school; Whirl numbers & 18s cadence; exact 120s/60s submerge timers.
- **Leotheras:** exact per-form durations (45/60 vs 60/60); Inner Demon window (~30s) & whisper
  timing (~25s) — second source was a modified-server wiki; Chaos Blast numbers; FR targets.
- **Karathress/Morogrim:** Cataclysmic Bolt interrupt-vs-heal convention; Sharkkis pet exact
  names; Earthquake/Watery Grave timers; Caribdis Cyclone name/duration; totem HP values.
- **Vashj:** all P1 ability damage ranges (single-snippet); Strider HP ~170k & fear cadence
  (single fan source); exact P3 add roster; Tainted Core "60s from kill" precise value.

**Recommendation:** ship the verified *mechanics/roles/kill-orders/prep* (high confidence);
keep exact numbers out of user-facing strat text (not actionable anyway) or gate them behind
a `"review": true` flag until a working-fetch pass confirms them.
