"""Fatigue modifier -- multi-dimensional: cardiovascular, muscular, mental, accumulated.

Fresh players get no penalty. As fatigue builds, shot percentages drop,
ball handling degrades, and defensive effort wanes. The four fatigue
dimensions affect different aspects of play:

- Cardiovascular: movement speed, recovery between actions
- Muscular: strength-based actions (dunks, post moves, screens)
- Mental: decision quality, focus, defensive reads
- Accumulated: season-level load, affects injury risk and baseline energy
"""

from __future__ import annotations

from basketball_sim.core.types import ActionContext, Modifier


def fatigue_modifier(context: ActionContext) -> Modifier:
    """Compute modifier based on player fatigue state.

    Returns a Modifier with penalties proportional to how tired the player is.
    A fully fresh player (all 1.0) returns a neutral modifier.
    """
    fatigue = context.attacker.fatigue

    # Weighted average of fatigue dimensions for each boost axis
    # Cardiovascular affects positioning (can't keep up) and rhythm
    cardio_drain = 1.0 - fatigue.cardiovascular

    # Muscular affects balance (weaker stance) and shot power
    muscular_drain = 1.0 - fatigue.muscular

    # Mental affects stance reads, help defense awareness
    mental_drain = 1.0 - fatigue.mental

    # Accumulated load is a multiplier on everything
    load_factor = 1.0 - fatigue.accumulated
    base_multiplier = 1.0 + load_factor * 0.3  # up to 30% worse when loaded

    # Offensive penalties (negative = attacker disadvantage when tired)
    # A tired ball handler loses effectiveness
    positioning_penalty = -(cardio_drain * 0.12 + muscular_drain * 0.05) * base_multiplier
    balance_penalty = -(muscular_drain * 0.08 + cardio_drain * 0.04) * base_multiplier
    rhythm_penalty = -(mental_drain * 0.06 + cardio_drain * 0.06) * base_multiplier

    # Shot percentage drops significantly with fatigue
    shot_penalty = -(
        cardio_drain * 0.04
        + muscular_drain * 0.03
        + mental_drain * 0.02
    ) * base_multiplier

    # Defensive fatigue of the DEFENDER helps the attacker
    def_fatigue = context.defender.fatigue
    def_cardio_drain = 1.0 - def_fatigue.cardiovascular
    def_muscular_drain = 1.0 - def_fatigue.muscular
    def_mental_drain = 1.0 - def_fatigue.mental

    # Tired defender = easier to beat
    def_positioning_bonus = def_cardio_drain * 0.10
    def_balance_bonus = def_muscular_drain * 0.08
    def_stance_bonus = def_mental_drain * 0.06

    tags: list[str] = []
    avg_attacker_fatigue = (cardio_drain + muscular_drain + mental_drain) / 3.0
    avg_defender_fatigue = (def_cardio_drain + def_muscular_drain + def_mental_drain) / 3.0

    if avg_attacker_fatigue > 0.6:
        tags.append("gassed")
    elif avg_attacker_fatigue > 0.35:
        tags.append("winded")

    if avg_defender_fatigue > 0.6:
        tags.append("defender_gassed")
    elif avg_defender_fatigue > 0.35:
        tags.append("defender_winded")

    return Modifier(
        positioning_boost=positioning_penalty + def_positioning_bonus,
        balance_boost=balance_penalty + def_balance_bonus,
        stance_boost=def_stance_bonus,
        rhythm_boost=rhythm_penalty,
        shot_pct_boost=shot_penalty,
        tags=tags,
    )
