"""Tendencies modifier -- player-specific habits and preferences.

Models how a player's natural tendencies affect their effectiveness.
A player going to their preferred side is more effective. A player
forced into an action that doesn't match their style is less effective.
"""

from __future__ import annotations

from basketball_sim.core.types import ActionContext, ActionType, Modifier


def tendencies_modifier(context: ActionContext) -> Modifier:
    """Compute modifier based on player tendencies and current action."""
    tendencies = context.attacker.tendencies
    action = context.action

    positioning_boost = 0.0
    balance_boost = 0.0
    rhythm_boost = 0.0
    shot_boost = 0.0
    tags: list[str] = []

    # --- Drive direction preference ---
    if action.action_type == ActionType.DRIBBLE_MOVE:
        move_direction = action.data.get("direction", "")
        if move_direction == "left":
            pref = tendencies.drive_direction.get("left", 0.5)
            # Strong preference = bonus, weak preference = penalty
            direction_effect = (pref - 0.5) * 0.10
            positioning_boost += direction_effect
            if pref > 0.7:
                tags.append("going_to_strong_hand")
            elif pref < 0.3:
                tags.append("going_to_weak_hand")
        elif move_direction == "right":
            pref = tendencies.drive_direction.get("right", 0.5)
            direction_effect = (pref - 0.5) * 0.10
            positioning_boost += direction_effect
            if pref > 0.7:
                tags.append("going_to_strong_hand")
            elif pref < 0.3:
                tags.append("going_to_weak_hand")

    # --- ISO frequency match ---
    if action.action_type == ActionType.DRIBBLE_MOVE:
        # Players who ISO a lot are better at it
        iso_comfort = tendencies.iso_frequency
        positioning_boost += (iso_comfort - 0.3) * 0.06
        balance_boost += (iso_comfort - 0.3) * 0.03

    # --- Flashy play tendency ---
    move_id = action.data.get("move", "")
    flashy_moves = {"behind_the_back", "spin_move", "shamgod", "through_the_legs"}
    if move_id in flashy_moves:
        flashy_comfort = tendencies.flashy_play_tendency
        # Flashy players execute flashy moves better
        positioning_boost += (flashy_comfort - 0.2) * 0.08
        if flashy_comfort > 0.6:
            tags.append("showtime")

    # --- Shot selection tendencies ---
    if action.action_type == ActionType.SHOT:
        shot_type = action.data.get("shot_type", "")
        if "three" in shot_type:
            # Players who prefer threes shoot them better
            three_pref = tendencies.three_vs_midrange
            shot_boost += (three_pref - 0.5) * 0.04
            if three_pref > 0.7:
                tags.append("in_comfort_zone")
        else:
            # Midrange preference
            mid_pref = 1.0 - tendencies.three_vs_midrange
            shot_boost += (mid_pref - 0.5) * 0.04

    # --- Pass-first vs score-first ---
    if action.action_type == ActionType.PASS:
        pass_pref = 1.0 - tendencies.pass_first_vs_score
        # Pass-first players are better passers
        positioning_boost += pass_pref * 0.03  # less relevant for passes, but helps vision
    elif action.action_type == ActionType.SHOT:
        score_pref = tendencies.pass_first_vs_score
        shot_boost += (score_pref - 0.5) * 0.02

    # --- Heat check tendency ---
    if action.action_type == ActionType.SHOT:
        # If the player just made shots and has high heat check tendency,
        # they'll take riskier shots but with confidence
        heat_check = tendencies.heat_check_tendency
        momentum = context.attacker.mental.momentum
        if momentum > 0.3 and heat_check > 0.5:
            shot_boost += heat_check * momentum * 0.03
            if heat_check > 0.7 and momentum > 0.5:
                tags.append("heat_check")

    # --- Off-ball movement quality ---
    # This affects the context for passes more than direct actions
    off_ball = tendencies.off_ball_movement_quality
    if off_ball > 0.7:
        rhythm_boost += 0.02  # good movers create better rhythm

    return Modifier(
        positioning_boost=positioning_boost,
        balance_boost=balance_boost,
        rhythm_boost=rhythm_boost,
        shot_pct_boost=shot_boost,
        tags=tags,
    )
