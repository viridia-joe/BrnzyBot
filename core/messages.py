"""
BrnzyBot flavor messages — Gnomish and Goblin Engineering themed.

Used as thinking/status messages while the optimizer runs.
Sourced from deep within the Tinkers' Union archives and several
voided Goblin Engineering warranties.
"""

import random

DISCORD_MAX = 2000


def chunk(text: str, limit: int = DISCORD_MAX) -> list[str]:
    """Split text into Discord-safe chunks (≤limit), breaking on newlines where possible."""
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    while text:
        if len(text) <= limit:
            parts.append(text)
            break
        split = text.rfind("\n", 0, limit)
        if split <= 0:               # no newline in window → try a word boundary
            split = text.rfind(" ", 0, limit)
        if split <= 0:               # no break point → hard cut
            split = limit
        parts.append(text[:split])
        text = text[split:].lstrip("\n")
    return parts

THINKING_MESSAGES = [
    # --- Gnomish Engineering (precision, overengineering, polite disasters) ---
    "Recalibrating the Hyper-Dimensional Gear Matrix. Please stand by. Do not tap the glass.",
    "Initializing Gnomish Combinatorial Analysis Engine v7.4.2. "
        "(v7.4.1 is discontinued after the incident.)",
    "Deploying Zapthrottle Item Evaluator... nominal... nominal... "
        "WARNING: mild sparking detected. Continuing.",
    "Overclock engaged. Thermaplugg's ghost has lodged a formal complaint. Proceeding anyway.",
    "The Gnomish Death Ray of Gear Analysis has been aimed at your equipment. "
        "85% chance it hits your gear. 15% chance it hits you.",
    "Initializing the Multi-Planar Optimization Sequencer. "
        "If you smell ozone, that's normal. If you smell burning hair, evacuate.",
    "Running upgrade analysis. NOTICE: This device has not been approved by the Tinkers' Union. "
        "High Tinker Mekkatorque sends his regards anyway.",
    "Cross-referencing 847 item permutations. "
        "Jeeves has been dispatched. He will arrive when he arrives.",
    "Gnomish precision analysis underway. Unlike our Goblin colleagues, "
        "we guarantee fewer than three explosions per solve.",
    "Transmitting gear data to the Deeprun Tram Computational Annex. "
        "Tram is currently on time. This is unprecedented. Do not panic.",
    "Set bonus interactions fully mapped. The math is fine. "
        "The math has always been fine. Please stop asking about the math.",
    "Phase 1: Item candidate generation. Complete. "
        "Phase 2: Constraint formulation. Complete. "
        "Phase 3: Praying to Mimiron. In progress.",
    "Recalibrating hit cap thresholds. Adjusting for lack of Shadow Priest. "
        "Adjusting for lack of Totem of Wrath. Adjusting for general misfortune.",
    "Gear matrix loaded. Socket bonus thresholds calibrated. "
        "Activating Hyper-Speed Solve Subroutines. "
        "Note: 'Hyper-Speed' refers to the calculation, not the delivery of results.",
    "Consulting the Gnomish Universal Remote for compatible set bonuses. "
        "Several unexpected devices have responded. Ignoring them.",

    # --- Goblin Engineering (explosives, profit motive, aggressive optimism) ---
    "Time is money, friend. Running profit-loss analysis on your entire gear loadout.",
    "Gear evaluation in progress. Goblin engineering disclaimer: "
        "results may vary. Explosions are a feature, not a bug.",
    "Activating Nitro-Boosted Solve Subroutine. Hold onto your goggles.",
    "One (1) goblin has been harmed in the making of this calculation. "
        "He considered it an acceptable loss.",
    "The Combinatorial Engine has consumed your gear list. "
        "It will return with optimal swap recommendations, or a small crater. Outcome: pending.",
    "Binary integer program initialized. If you are reading this message, "
        "the explosion was small enough that the results survived.",
    "Routing optimization request through the Gadgetzan Neutral Auction Annex. "
        "Goblins are involved. The 15% processing fee has been waived. This time.",
    "Loot-A-Rang probability matrix engaged. "
        "Please ensure all nearby upgrades are within throwing distance.",

    # --- Mixed / Faction-neutral engineering chaos ---
    "The HiGHS solver has been fed your gear data. It is processing. "
        "It is always processing. We do not know how to make it stop.",
    "Gear solve queued behind seventeen other requests from raiders "
        "who also believe they are the main character. Estimated wait: shortly.",
]


def thinking() -> str:
    """Return a random engineering-flavored thinking message."""
    return random.choice(THINKING_MESSAGES)


def thinking_for(character: str) -> str:
    """Return a thinking message with optional character name injection."""
    msg = random.choice(THINKING_MESSAGES)
    return msg
