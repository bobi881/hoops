"""Psychology modifier -- confidence, frustration, focus, momentum, intimidation.

Models the basketball that happens between the ears. A confident player
on a hot streak plays differently than a frustrated player who just got
his shot blocked. Veterans maintain composure under pressure; young
players can crumble or explode.
"""

from __future__ import annotations

from basketball_sim.core.types import ActionContext, Modifier


def psychology_modifier(context: ActionContext) -> Modifier:
    """Compute modifier based on attacker and defender mental states."""
    atk_mental = context.attacker.mental
    def_mental = context.defender.mental

    # --- Attacker confidence ---
    # Confidence above 0.5 is a bonus, below is a penalty
    # Range: -0.08 to +0.08
    confidence_effect = (atk_mental.confidence - 0.5) * 0.16

    # --- Momentum ---
    # Positive momentum helps, negative hurts
    # Range: -0.06 to +0.06
    momentum_effect = atk_mental.momentum * 0.06

    # --- Focus ---
    # High focus improves everything slightly; low focus hurts
    # Range: -0.05 to +0.05
    focus_effect = (atk_mental.focus - 0.5) * 0.10

    # --- Frustration ---
    # Frustration is purely negative for the player experiencing it
    # High frustration = forcing bad shots, sloppy handles
    frustration_penalty = -atk_mental.frustration * 0.08

    # --- Intimidation ---
    # Being intimidated reduces aggressiveness and shot confidence
    intimidation_penalty = -atk_mental.intimidation * 0.06

    # --- Composure under pressure ---
    # High composure dampens negative effects
    composure_factor = 0.5 + atk_mental.composure * 0.5  # 0.5 to 1.0
    # Composure reduces the impact of frustration and intimidation
    frustration_penalty *= (1.0 - atk_mental.composure * 0.4)
    intimidation_penalty *= (1.0 - atk_mental.composure * 0.5)

    # --- Defender psychology ---
    # Frustrated defenders overcommit (good for attacker)
    def_frustration_bonus = def_mental.frustration * 0.06
    # Intimidated defenders back off
    def_intimidation_bonus = def_mental.intimidation * 0.04

    # Combine effects
    total_positioning = (
        confidence_effect * 0.5
        + momentum_effect * 0.5
        + frustration_penalty * 0.3
        + def_frustration_bonus
    )
    total_balance = (
        confidence_effect * 0.3
        + def_frustration_bonus * 0.5
        + def_intimidation_bonus * 0.5
    )
    total_rhythm = (
        momentum_effect * 0.4
        + focus_effect * 0.6
        + frustration_penalty * 0.4
    )
    total_shot = (
        confidence_effect * 0.5
        + momentum_effect * 0.3
        + focus_effect * 0.4
        + frustration_penalty * 0.5
        + intimidation_penalty * 0.5
    )

    tags: list[str] = []
    if atk_mental.confidence > 0.8:
        tags.append("feeling_it")
    if atk_mental.confidence < 0.25:
        tags.append("shook")
    if atk_mental.momentum > 0.6:
        tags.append("on_fire")
    if atk_mental.momentum < -0.5:
        tags.append("ice_cold")
    if atk_mental.frustration > 0.7:
        tags.append("frustrated")
    if atk_mental.intimidation > 0.6:
        tags.append("intimidated")
    if def_mental.frustration > 0.6:
        tags.append("defender_frustrated")
    if atk_mental.composure > 0.85 and atk_mental.frustration > 0.3:
        tags.append("composed_under_pressure")

    return Modifier(
        positioning_boost=total_positioning,
        balance_boost=total_balance,
        rhythm_boost=total_rhythm,
        shot_pct_boost=total_shot,
        tags=tags,
    )
