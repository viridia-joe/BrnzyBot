"""
Boss guide data for SSC (Serpentshrine Cavern) and TK (Tempest Keep: The Eye).

Each BossEntry contains:
  - full_name, raid, boss_num: display info
  - aliases: fuzzy match strings
  - has_diagram: whether a position diagram should be generated
  - roles: how many of each role type the fight needs (used for assignment hints)
  - context: injected into Claude's system prompt for assignment generation
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class BossEntry:
    full_name: str
    raid: str
    boss_num: int
    has_diagram: bool
    aliases: List[str]
    context: str
    roles: Dict[str, int]  # role label -> count hint


# ---------------------------------------------------------------------------
# All bosses
# ---------------------------------------------------------------------------

BOSS_DATA: Dict[str, BossEntry] = {

    "hydross": BossEntry(
        full_name="Hydross the Unstable",
        raid="SSC",
        boss_num=1,
        has_diagram=True,
        aliases=["hydross", "hydross the unstable", "hyd"],
        roles={"tanks": 3, "tank_healers": 4, "raid_healers": 2, "hunters": 2},
        context="""\
FIGHT: Hydross the Unstable — SSC Boss 1

KEY MECHANICS:
- Two forms: Frost and Poison. Transitions every ~4 debuff stacks (~60 sec).
- THREAT RESETS on every transition — DPS must STOP ALL DAMAGE AND DOTS 3 sec before.
- Frost form: Water Tomb — places random targets in water globes; raid must SPREAD 8 yd apart.
- Poison form: Vile Sludge — frontal cone; tank faces away from raid.
- Each transition spawns 4 Corrupted Elementals. Add tank picks them all up and AoEs them down.

ROLES NEEDED (assign these):
- {square} Frost MT: 1 warrior or paladin. Tanks Hydross between the two pillars in Frost form.
- {triangle} Nature MT: 1 warrior or paladin. Taunts at ~4 stacks and walks Hydross across the flag boundary line into Poison form.
- {cross} Add OT: 1 warrior. Picks up all 4 Corrupted Elementals each transition, holds them for AoE.
- Frost MT healers: 2 healers dedicated to Frost MT.
- Nature MT healers: 2 healers dedicated to Nature MT.
- Raid/Add healers: 1-2 healers covering the add OT and raid.
- Misdirect hunters: 2 hunters — one MDs for Frost MT pull, one MDs for first transition taunt.
- Melee: Stay behind boss at all times. On transition, STOP ALL DAMAGE AND DOTS 3 sec before.
  Follow the boss across the boundary line — move with the Nature MT after the taunt.
  In Poison form, AoE down the 4 elementals before returning to boss.

ASSIGNMENT FORMAT RULES:
- Use {square} for Frost MT, {triangle} for Nature MT, {cross} for Add OT.
- List healers grouped by who they're healing.
- Put MD chain on its own line.
- Include a MELEE section: where to stand and transition behavior.
- End with 4-5 short bullet rules.
""",
    ),

    "lurker": BossEntry(
        full_name="The Lurker Below",
        raid="SSC",
        boss_num=2,
        has_diagram=True,
        aliases=["lurker", "lurker below", "the lurker below", "lurker-below", "tlb"],
        roles={"tanks": 2, "tank_healers": 3, "raid_healers": 3},
        context="""\
FIGHT: The Lurker Below — SSC Boss 2

KEY MECHANICS:
- Pulled by someone fishing at the pool in the center. No normal aggro pull.
- SPOUT: Lurker rotates 360°, knocking back anyone hit. Everyone (melee AND ranged) JUMPS IN WATER to avoid.
- WHIRL: Close-range AoE spin on melee. Melee should be ready to take it or step back.
- GEYSER: Shoots a water geyser at a random target — heal through.
- P2 (SUBMERGE ~every 90 sec): Lurker submerges for ~1 min. 9 Coilfang Nagas spawn on 3 outer platforms (3 per platform). Tank picks up nearest. Ranged AoE. Lurker re-emerges.
- MT stands behind center pillar to avoid direct hits.

ROLES NEEDED:
- {skull} MT: 1 warrior or paladin. Tanks Lurker from behind the center pillar.
- {cross} Naga OT: 1 tank for P2 Naga adds. Picks up ~3 nagas on nearest platform.
- MT healers: 2-3 dedicated healers on MT.
- Raid healers: 2-3 healers covering spout/whirl splash + raid.
- No interrupts or specialty roles needed.

ASSIGNMENT FORMAT RULES:
- Use {skull} for MT, {cross} for Naga OT.
- Include a reminder that EVERYONE jumps in water on Spout.
- Note that ranged can stay in water if needed to dodge Whirl.
""",
    ),

    "morogrim": BossEntry(
        full_name="Morogrim Tidewalker",
        raid="SSC",
        boss_num=3,
        has_diagram=True,
        aliases=["morogrim", "morogrim tidewalker", "tide", "moro", "tidewalker"],
        roles={"tanks": 2, "tank_healers": 3, "raid_healers": 3, "cc": 2},
        context="""\
FIGHT: Morogrim Tidewalker — SSC Boss 3

KEY MECHANICS:
- Earthquake: AoE knockdown every ~30 sec. Immediately after, murloc packs (4 packs, 1 per corner) spawn.
- Murlocs MUST be AoE'd down before the next Earthquake or the fight snowballs.
- Watery Grave: Puts 4 random players in bubbles near the walls — dedicated healers watch these.
- Phase 2 (25% HP): Boss moves toward entrance/ramp. Watery Globules spawn (slow projectiles) — kite or LoS them.
- Murloc CC backup: mage Sheep or hunter Trap if adds get out of hand.

ROLES NEEDED:
- {skull} MT: 1 warrior or paladin. Tanks Morogrim center, moves to entrance at 25%.
- {cross} Murloc OT: 1 warrior/paladin/druid. Runs to gather all 4 murloc packs after each Earthquake.
- MT healers: 2-3 dedicated healers on MT.
- Raid/Grave healers: 2-3 healers watching Watery Grave targets and general raid.
- CC backup: 1 mage (Sheep) and/or 1 hunter (Trap) for emergency murloc control.
- Misdirect hunter: 1 hunter with MD for MT pull.

ASSIGNMENT FORMAT RULES:
- Use {skull} for MT, {cross} for Murloc OT.
- Call out AoE priority on murlocs explicitly.
- Note 25% phase transition (move to entrance).
""",
    ),

    "karathress": BossEntry(
        full_name="Fathom-Lord Karathress",
        raid="SSC",
        boss_num=4,
        has_diagram=True,
        aliases=["karathress", "fathom lord", "fathom-lord karathress", "fathom", "flk"],
        roles={"tanks": 4, "tank_healers": 5, "raid_healers": 2, "interrupts": 4},
        context="""\
FIGHT: Fathom-Lord Karathress — SSC Boss 4

KEY MECHANICS:
- 4 mobs fight simultaneously. Each must be tanked separately.
- Kill order: Tidalvess → Sharkkis → Caribdis → Karathress.
- When each adviser dies, Karathress absorbs their ability — plan for this.
- Tidalvess (kill 1st): Drops totems constantly — Windfury totem must be killed immediately.
- Sharkkis (kill 2nd): Has a hunter pet that enrages at low HP. Keep pet away from raid.
- Caribdis (kill 3rd): Heals with Healing Wave and knocks back with Tidal Surge. Interrupt Healing Wave.
- Karathress (kill 4th): Gains the absorbed abilities of all dead advisers.

ROLES NEEDED:
- {skull} Karathress tank: 1 warrior/paladin. Holds Karathress throughout — he's just the kill target last.
- {cross} Sharkkis + pet tank: 1 warrior/paladin. Keeps Sharkkis and his pet in a corner, away from raid.
- {triangle} Tidalvess tank: 1 warrior/paladin. Pulls Tidalvess first and holds for kill.
- {moon} Caribdis tank: 1 warrior/paladin. Keeps Caribdis in FAR corner, away from all.
- Healers: 2 per tank pair.
- Interrupt team (Caribdis Healing Wave): 3-4 players — shaman, rogue, warrior.
- Misdirect hunters: 2 hunters for initial pulls.

ASSIGNMENT FORMAT RULES:
- Use {skull}={cross}={triangle}={moon} for each of the 4 bosses.
- List kill order prominently.
- Call out totem-kill responsibility and Caribdis interrupt team by name.
""",
    ),

    "leotheras": BossEntry(
        full_name="Leotheras the Blind",
        raid="SSC",
        boss_num=5,
        has_diagram=True,
        aliases=["leotheras", "leo", "leotheras the blind", "leothe", "the blind"],
        roles={"tanks": 2, "tank_healers": 3, "raid_healers": 3},
        context="""\
FIGHT: Leotheras the Blind — SSC Boss 5

KEY MECHANICS:
- Two forms alternating every 60 sec: Humanoid form and Demon form.
- Humanoid form: Normal tank-and-spank. Whirlwind warning before form swap — RAID SPREADS IMMEDIATELY (30 yd minimum).
- During Whirlwind: Inner Demons spawn on each player. EACH PLAYER KILLS THEIR OWN INNER DEMON. If you fail to kill it before the form swap, you get Mind Controlled.
- Demon form: Chaos Blast — fire/shadow AoE nuke on tank. Requires Fire Resistance set (300+ FR buffed ideally). Humanoid tank does NOT fight in demon form.
- 15% phase: Both forms are active simultaneously. Zerg human form down — demon despawns when human dies.
- Banish the demon form while killing inner demons (warlocks).

ROLES NEEDED:
- {skull} Humanoid MT: 1 warrior or paladin. Tanks humanoid form.
- {cross} Demon FR Tank: 1 warrior or paladin in Fire Resistance gear (~365 FR buffed). Taunts during Demon form.
- Humanoid MT healers: 2-3 healers.
- Demon FR tank healers: 2-3 healers — extra heals needed for Chaos Blast.
- Raid healers: 1-2 for inner demon phase splash.

ASSIGNMENT FORMAT RULES:
- Use {skull} for Humanoid MT, {cross} for Demon FR Tank.
- Strongly emphasize: KILL YOUR INNER DEMON.
- Note Ice Block / Feign Death remove the bleed.
- Note 15% both-forms-simultaneously burn phase.
""",
    ),

    "vashj": BossEntry(
        full_name="Lady Vashj",
        raid="SSC",
        boss_num=6,
        has_diagram=True,
        aliases=["vashj", "lady vashj", "the snake lady", "snake lady", "vasj"],
        roles={"tanks": 3, "tank_healers": 4, "raid_healers": 3, "cube_catchers": 4, "kiters": 1},
        context="""\
FIGHT: Lady Vashj — SSC Boss 6 (Final)

KEY MECHANICS:
P1 (100%→70%): Tank-and-spank. Static Charge targets a random player — run AWAY from raid.
Shaman drops Grounding Totem in tank group to eat Shock Blasts.

P2 (70%→50%): SHIELD PHASE. Four generators around the platform must be deactivated.
- Tainted Elementals spawn — ranged kills them fast (15 sec before they corrupt the water).
- When a Tainted Elemental dies, it drops a Tainted Core (looks like a green orb).
- A designated player picks up the Tainted Core → they get rooted → they THROW it to the generator Catcher.
- The Catcher runs to the Generator and clicks it to deactivate it.
- Coilfang Elites spawn in the center — need a tank to hold them.
- Coilfang Striders spawn and chase random players — need a kiter running wide circles around the platform edge.
- Enchanted Elementals also spawn and must be killed before they reach Vashj or she heals.
P3 (50%→0%): Vashj re-engages. Spore Bats spawn periodically. Standard DPS burn with Bloodlust.

ROLES NEEDED:
- {skull} MT (P1 & P3): 1 warrior. Main tanks Vashj.
- {cross} P2 Elite Tank: 1 warrior. Holds Coilfang Elites during shield phase at center.
- {triangle} Strider Kiter: 1 hunter/rogue/feral — kites Striders in wide circle around platform edge.
- Generator Catchers (4 named players, one per generator: NW, NE, SE, SW): Stand near their generator, receive the thrown Tainted Core, click the generator.
- Tainted Elemental kill team: 3-4 ranged DPS.
- Enchanted Elemental killers: 4 ranged DPS assigned by quadrant (N, E, S, W).
- MT healers (P1/P3): 2-3 healers.
- Elite tank healers (P2): 2 healers.
- Raid healers: 2-3 covering P2 chaos.

ASSIGNMENT FORMAT RULES:
- Use {skull} for MT, {cross} for Elite Tank.
- Name all 4 cube catchers with their generator quadrant (NW/NE/SE/SW).
- Name the Strider kiter explicitly.
- Keep P2 roles clearly separated from P1/P3.
- Include Bloodlust timing note (P3).
""",
    ),

    "alar": BossEntry(
        full_name="Al'ar",
        raid="TK",
        boss_num=1,
        has_diagram=True,
        aliases=["alar", "al'ar", "al ar", "phoenix god", "phoenix", "the phoenix"],
        roles={"tanks": 3, "tank_healers": 4, "raid_healers": 3},
        context="""\
FIGHT: Al'ar — Tempest Keep Boss 1

KEY MECHANICS:
P1 (100%→25%): Al'ar flies between 4 elevated platforms (numbered 1→2→3→4, counterclockwise).
- Only RANGED DPS can hit Al'ar during platform phase — melee cannot reach.
- Al'ar gains Flame Buffet stacks on tank — TWO tanks swap each platform shift.
- On each platform, tank A engages → tank B taunts when A has ~3 stacks → Al'ar flies to next platform → repeat.
- Ember of Al'ar adds spawn between platform shifts — Ground Tank picks them up on the ground.
- Embers self-resurrect if not killed (become Phoenix). Kill fast.

P2 (25%→0%): Al'ar crash-lands center. Normal tank-and-spank.
- Ember adds keep spawning — Ember Tank kites them away from raid (Ember Blast on death = AoE).
- Meteor: Red circle ground warning → move out immediately.
- Bloodlust/Heroism at P2 engagement.

ROLES NEEDED:
- {skull} Platform Tank A: 1 warrior. First to engage on each platform.
- {cross} Platform Tank B: 1 warrior/paladin. Taunts ~3 Flame Buffet stacks, swaps with A.
- {triangle} Ground/Ember Tank: 1 warrior/paladin. Handles Ember adds on the ground throughout. Kites Ember adds in P2.
- Platform tank healers: 2-3 following tanks across platforms.
- Ground/raid healers: 2-3 on ground covering adds and raid.
- Ranged DPS: primary damage dealers in P1 (melee stand by for P2).
- Misdirect hunter: 1 for P2 Al'ar pickup.

ASSIGNMENT FORMAT RULES:
- Use {skull} for Tank A, {cross} for Tank B, {triangle} for Ground Tank.
- Emphasize ranged-only P1 damage.
- Emphasize Ember add priority kill.
- Note Bloodlust at P2 pull.
""",
    ),

    "voidreaver": BossEntry(
        full_name="Void Reaver",
        raid="TK",
        boss_num=2,
        has_diagram=False,
        aliases=["void reaver", "voidreaver", "vr", "lootreaver"],
        roles={"tanks": 3, "tank_healers": 3, "raid_healers": 3},
        context="""\
FIGHT: Void Reaver — Tempest Keep Boss 2

KEY MECHANICS:
- Knock Away: Periodically knocks current tank back — next tank picks up immediately. 3 tanks rotating.
- Pounding: AoE raid-wide every ~12 sec for ~1500 dmg — just heal through, no mechanic to dodge.
- Arcane Orbs: Fall from ceiling targeting random players — watch sky, MOVE OUT of purple circle. Kill neighboring players if you don't.
- Void Reaver is NOT TAUNTABLE — tanks naturally rotate via Knock Away; next tank must be in melee and on high threat.
- 10-minute hard enrage — DPS check is real but not punishing.

ROLES NEEDED:
- {skull} Tank 1: 1 warrior. First tank — highest threat to start.
- {cross} Tank 2: 1 warrior/paladin. Second in rotation.
- {triangle} Tank 3: 1 warrior/paladin. Third in rotation. All three stay in melee range behind boss.
- Tank healers: 1 per tank, plus 1 raid healer.
- Raid healers: 2-3 covering Pounding AoE.
- Misdirect chain: 3 hunters, one per tank in rotation order.

ASSIGNMENT FORMAT RULES:
- Use {skull}/{cross}/{triangle} for the 3 tanks.
- List MD chain for each tank swap.
- Remind raid to spread and watch Arcane Orbs.
- Note boss is not tauntable — rotation is natural.
""",
    ),

    "solarian": BossEntry(
        full_name="High Astromancer Solarian",
        raid="TK",
        boss_num=3,
        has_diagram=True,
        aliases=["solarian", "high astromancer solarian", "astromancer", "sol", "solar"],
        roles={"tanks": 2, "tank_healers": 3, "raid_healers": 3, "interrupts": 3},
        context="""\
FIGHT: High Astromancer Solarian — Tempest Keep Boss 3

KEY MECHANICS:
- Wrath of the Astromancer: Targeted player gets a growing AoE debuff. That player RUNS TO THE FAR WALL immediately — explodes for massive AoE on the 8 yd radius when it pops.
- Arcane Missiles: Random target — just heal through.
- Add Phase (every ~50 sec): Solarian disappears. 3 portals open (North, Southwest, Southeast). Priests and casters spawn. AoE down fast — Interrupt Priest heals!
- Solarian returns after ~30 sec with 2 Priests on top of her.
- Phase 2 (20% HP): Solarian becomes a Voidwalker. Fear AoE — Tremor Totem / Fear Ward. No portals. Bloodlust here.

ROLES NEEDED:
- {skull} MT (Solarian): 1 warrior. Tanks Solarian — faces her away from raid.
- {cross} Add Tank: 1 warrior/paladin. Picks up Priests from all 3 portals during add phase.
- MT healers: 2-3.
- Raid healers: 2-3 covering Wrath targets and add phase.
- Interrupt team (Priest heals during add phase): 3-4 players — shaman/rogue/warrior.
- Fear Ward: 1 priest casts on MT for P2. Tremor Totem: shaman in MT group.
- Misdirect: 1 hunter for MT pull.

ASSIGNMENT FORMAT RULES:
- Use {skull} for MT, {cross} for Add Tank.
- Name interrupt team explicitly.
- Note Wrath mechanic: target RUNS AWAY from raid.
- Note Bloodlust at 20%.
""",
    ),

    "kaelthas": BossEntry(
        full_name="Kael'thas Sunstrider",
        raid="TK",
        boss_num=4,
        has_diagram=True,
        aliases=["kaelthas", "kael'thas", "kael", "kaelthas sunstrider", "kael thas", "kt", "sunstrider"],
        roles={"tanks": 4, "tank_healers": 5, "raid_healers": 3, "interrupts": 3},
        context="""\
FIGHT: Kael'thas Sunstrider — Tempest Keep Boss 4 (Final) — 5-PHASE FIGHT

P1: ADVISORS (one at a time, kill order: Thaladred → Sanguinar → Capernian → Telonicus)
- Thaladred the Darkener: Has Gaze — he fixates a target and pursues them. Designated kiter runs Thaladred AROUND the edge of the room, away from raid. Kill in back corner (corpse stays there for P3).
- Lord Sanguinar: Tank-and-spank. Bellowing Roar (fear) — Fear Ward on tank. Healers/ranged stay 30 yd back.
- Capernian: Caster — "Lock-tank" by a warlock using Sacrifice void walker for tankiness. Arcane AoE around her tank — keep healers 30+ yd back.
- Telonicus: Drops Remote-Controlled Bombs on ground. Melee watches feet. Tank holds him.

P2: 7 LEGENDARY WEAPONS spawn and fight the raid (~3 min). DPS each weapon until dead. DO NOT LOOT UNLESS ASSIGNED.
- Cosmic Infuser → MT
- Phaseshift Bulwark → 2nd tank
- Devastation (mace) → 3rd tank
- Staff of Disintegration → warlock/designated (activate aura: immunity to silence/stun)
- Remaining 3: Verdant Sphere (wipe DPS), Lady Vashj's Venom Bolt, Thori'dal (bow) — any available player
- Aura activation: Assigned players RIGHT-CLICK their legendary immediately after looting.

P3: All 4 Advisors RESURRECT simultaneously at full HP. HARDEST PHASE.
- Same kill order: Thaladred → Sanguinar → Capernian → Telonicus.
- Tanks pre-position near corpses before P3 starts.
- BLOODLUST/HEROISM here.

P4 (under ~50%): Kael'thas himself engages.
- Phoenix tank: 1 tank kites the Phoenix away from raid while ranged kills it.
- Phoenix Egg: ranged kills egg in 15 sec or Phoenix rezzes.
- Pyroblast: INTERRUPT on tank group OR Shield aura from legendary weapon.
- Fireball: tank faces away from raid.

P5 (Gravity Lapse, repeats 2-3 times):
- Everyone floats. Spread MAX distance apart (Nether Beam chains to nearest players).
- Nether Vapor clouds: DO NOT TOUCH.
- Land near ground when Lapse ends to reduce fall damage.

ROLES NEEDED:
- {skull} Thaladred Kiter: NOT a tank — typically a hunter or warrior who kites Thaladred around room edge.
- {cross} Sanguinar Tank: 1 warrior. Standard tank.
- {triangle} Capernian Handler: 1 warlock (lock-tank with Sacrifice). If no warlock, a warrior.
- {moon} Telonicus Tank: 1 warrior/paladin.
- {star} P4 MT (Kael'thas): 1 warrior. Main tank for Kael'thas himself.
- {square} Phoenix Tank: 1 tank/hunter who kites the Phoenix away during P4.
- Legendary weapon assignments: name who gets each of the 7 weapons (esp. Staff for aura).
- Interrupt team (Pyroblast): 3 players near MT — shaman/rogue/warrior.
- Healers: 2 per tank group, 2 raid healers.
- Misdirect: 3 hunters for P1 and P4 pickups.

ASSIGNMENT FORMAT RULES:
- Use {skull}/{cross}/{triangle}/{moon}/{star}/{square} for the 6 different roles.
- List P1 advisor assignments clearly with kill order.
- List weapon assignments for P2 (who gets which legendary).
- Note BLOODLUST in P3.
- Keep Gravity Lapse rules concise.
""",
    ),
}


# ---------------------------------------------------------------------------
# Alias → canonical key lookup
# ---------------------------------------------------------------------------

_ALIAS_MAP: Dict[str, str] = {}
for _key, _entry in BOSS_DATA.items():
    for _alias in _entry.aliases:
        _ALIAS_MAP[_alias.lower()] = _key


def resolve_boss(name: str) -> str | None:
    """Return canonical boss key for a given name/alias, or None if not found."""
    normalized = name.lower().strip()
    if normalized in BOSS_DATA:
        return normalized
    if normalized in _ALIAS_MAP:
        return _ALIAS_MAP[normalized]
    # Partial substring match
    for alias, key in _ALIAS_MAP.items():
        if normalized in alias or alias in normalized:
            return key
    return None


# Ordered list for autocomplete display
BOSS_DISPLAY_ORDER = [
    ("hydross",     "Hydross the Unstable"),
    ("lurker",      "The Lurker Below"),
    ("morogrim",    "Morogrim Tidewalker"),
    ("karathress",  "Fathom-Lord Karathress"),
    ("leotheras",   "Leotheras the Blind"),
    ("vashj",       "Lady Vashj"),
    ("alar",        "Al'ar"),
    ("voidreaver",  "Void Reaver"),
    ("solarian",    "High Astromancer Solarian"),
    ("kaelthas",    "Kael'thas Sunstrider"),
]
