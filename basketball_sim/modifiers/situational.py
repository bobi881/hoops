"""Situational modifier -- clutch time, home court, score differential.

Models how the game situation affects play quality. Clutch time
amplifies everything: great players get better, others tighten up.
Home court provides a subtle edge. Blowouts affect effort.
"""

from __future__ import annotations

from basketball_sim.core.types import ActionContext, Modifier


def situational_modifier(context: ActionContext) -> Modifier:
    """Compute modifier based on game situation."""
    game = context.game_state
    possession = context.possession
    attacker = context.attacker

    tags: list[str] = []
    positioning_boost = 0.0
    balance_boost = 0.0
    rhythm_boost = 0.0
    shot_boost = 0.0

    # --- Clutch time ---
    # Last 2 minutes of 4th quarter or OT with score within 5
    is_fourth_or_later = game.quarter >= 4
    time_remaining = game.game_clock
    score_diff = abs(game.score.get("home", 0) - game.score.get("away", 0))

    is_clutch = is_fourth_or_later and time_remaining <= 120.0 and score_diff <= 5
    is_late_game = is_fourth_or_later and time_remaining <= 300.0

    if is_clutch:
        tags.append("clutch_time")
        # Clutch usage tendency determines if this helps or hurts
        clutch_usage = attacker.tendencies.clutch_usage
        composure = attacker.mental.composure

        # Great clutch players thrive, others tighten up
        clutch_effect = (clutch_usage - 0.5) * 0.10 + (composure - 0.5) * 0.08
        shot_boost += clutch_effect
        positioning_boost += clutch_effect * 0.5

        if clutch_usage > 0.7 and composure > 0.7:
            tags.append("clutch_gene")
        elif clutch_usage < 0.3 or composure < 0.3:
            tags.append("tight")
    elif is_late_game:
        tags.append("crunch_time")

    # --- Score differential ---
    if possession.offensive_team_id == game.home_team.team_id:
        our_score = game.score.get("home", 0)
        their_score = game.score.get("away", 0)
    else:
        our_score = game.score.get("away", 0)
        their_score = game.score.get("home", 0)

    diff = our_score - their_score

    if diff > 20:
        # Blowout -- offense may coast, garbage time
        tags.append("garbage_time")
        rhythm_boost -= 0.03
        positioning_boost -= 0.02
    elif diff > 10:
        tags.append("comfortable_lead")
        rhythm_boost += 0.01  # relaxed, in rhythm
    elif diff < -20:
        tags.append("desperation")
        shot_boost -= 0.02  # pressing, forcing
        positioning_boost += 0.02  # more aggressive
    elif diff < -10:
        tags.append("chasing")
        positioning_boost += 0.01

    # --- Home court advantage ---
    # Subtle but real: ~3 points per game in NBA
    is_home = possession.offensive_team_id == game.home_team.team_id
    if is_home:
        tags.append("home_court")
        shot_boost += 0.008  # slight home shooting boost
        rhythm_boost += 0.01  # crowd energy helps rhythm
    else:
        # Road team gets a very slight penalty
        shot_boost -= 0.005

    # --- Shot clock pressure ---
    shot_clock = possession.shot_clock
    if shot_clock <= 5.0:
        tags.append("shot_clock_winding")
        shot_boost -= 0.03  # rushed shots
        positioning_boost -= 0.02
    elif shot_clock <= 10.0:
        tags.append("shot_clock_low")

    # --- Quarter dynamics ---
    if game.quarter == 1 and time_remaining > 600:
        tags.append("early_game")
    elif game.quarter >= 4 and time_remaining <= 60:
        tags.append("final_minute")

    return Modifier(
        positioning_boost=positioning_boost,
        balance_boost=balance_boost,
        rhythm_boost=rhythm_boost,
        shot_pct_boost=shot_boost,
        tags=tags,
    )
