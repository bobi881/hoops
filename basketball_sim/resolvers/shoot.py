"""Shot resolver -- uses matchup state for contest calculation.

Determines shot percentage from player attributes, matchup state
(how open the shooter is), grid position, and modifiers.
"""

from __future__ import annotations

import random

from basketball_sim.core.grid import COURT
from basketball_sim.core.types import (
    ActionContext,
    ActionResult,
    AggregatedModifier,
    BallHandlerRhythm,
    DefenderBalance,
    DefenderPositioning,
    EventType,
    GameEvent,
    MatchupState,
)


def resolve_shot(
    matchup: MatchupState,
    agg: AggregatedModifier,
    context: ActionContext,
) -> ActionResult:
    """Resolve a shot attempt.

    The shot percentage is built from:
    1. Base percentage from player attributes + shot type
    2. Contest level derived from matchup positioning and balance
    3. Grid cell modifiers (corner three bonus, paint bonus, etc.)
    4. Aggregated modifier boost
    5. Catch-and-shoot vs off-dribble
    """
    rng = context.rng
    shooter = context.attacker
    cell = context.cell
    shot_data = context.action.data

    shot_type = shot_data.get("shot_type", "mid_range")
    is_three = "three" in shot_type
    point_value = 3 if is_three else 2

    # --- Base percentage from attributes ---
    if is_three:
        base_pct = shooter.attributes.three_point / 200.0  # 70 rating -> 0.35
    elif "layup" in shot_type or "dunk" in shot_type:
        base_pct = shooter.attributes.driving_layup / 150.0  # 70 -> 0.467
    else:
        base_pct = shooter.attributes.mid_range / 180.0  # 70 -> 0.389

    # --- Contest level from matchup state (continuous, not categorical) ---
    contest = _calculate_contest(matchup)
    # contest: 0.0 = wide open, 1.0 = heavily contested
    contest_penalty = contest * 0.15  # max 15% penalty at full contest

    # --- Grid cell modifiers ---
    cell_bonus = 0.0
    if COURT.is_valid(cell):
        cell_meta = COURT.get(cell)
        if cell_meta.is_corner_three and is_three:
            cell_bonus = 0.025  # corner threes are higher pct
        if cell_meta.is_restricted_area:
            cell_bonus = 0.08  # at the rim
        if cell_meta.is_paint and not cell_meta.is_restricted_area:
            cell_bonus = 0.03  # in the paint but not at rim

    # --- Rhythm modifier ---
    rhythm_mod = 0.0
    if matchup.rhythm == BallHandlerRhythm.ELEVATED:
        rhythm_mod = 0.01  # set shooter bonus
    elif matchup.rhythm == BallHandlerRhythm.ATTACKING:
        rhythm_mod = -0.02  # pull-up off the dribble penalty

    # --- Catch-and-shoot vs off-dribble ---
    # `catch_and_shoot_bonus` is added when shooting off a pass.
    # `off_dribble_penalty` is SUBTRACTED when shooting off the dribble;
    # the field name expresses a penalty so a positive value hurts the shot.
    catch_and_shoot = shot_data.get("catch_and_shoot", False)
    if catch_and_shoot:
        cs_mod = shooter.shooting.catch_and_shoot_bonus
    else:
        cs_mod = -shooter.shooting.off_dribble_penalty

    # --- Combine ---
    final_pct = (
        base_pct
        - contest_penalty
        + cell_bonus
        + rhythm_mod
        + cs_mod
        + agg.shot_pct_boost
    )

    # Hot zone check
    if cell in shooter.shooting.hot_zones:
        final_pct += shooter.shooting.hot_zones[cell]

    # Clamp between 0.02 (never impossible) and 0.95 (never guaranteed)
    final_pct = max(0.02, min(0.95, final_pct))

    # --- Roll ---
    made = rng.random() < final_pct

    # --- Generate events and tags ---
    tags: list[str] = list(agg.tags)

    attempt_event = GameEvent(
        event_type=EventType.SHOT_ATTEMPT,
        player_id=context.action.player_id,
        data={
            "shot_type": shot_type,
            "cell": cell,
            "point_value": point_value,
            "contest": round(contest, 2),
            "final_pct": round(final_pct, 3),
        },
        tags=["shot_attempt"],
    )

    if made:
        result_type = EventType.SHOT_MADE
        result_tags = ["shot_made"]
        if is_three:
            result_tags.append("three_pointer_made")
        if contest < 0.15:
            result_tags.append("wide_open")
        elif contest > 0.7:
            result_tags.append("contested_make")
            result_tags.append("tough_shot")
    else:
        result_type = EventType.SHOT_MISSED
        result_tags = ["shot_missed"]
        if is_three:
            result_tags.append("three_pointer_missed")

    tags.extend(result_tags)

    result_event = GameEvent(
        event_type=result_type,
        player_id=context.action.player_id,
        data={
            "shot_type": shot_type,
            "cell": cell,
            "points": point_value if made else 0,
            "contest": round(contest, 2),
        },
        tags=result_tags,
    )

    return ActionResult(
        events=[attempt_event, result_event],
        tags=tags,
        ends_possession=True,
        score_change=point_value if made else 0,
    )


def _calculate_contest(matchup: MatchupState) -> float:
    """Calculate contest level from matchup state.

    Returns 0.0 (wide open) to 1.0 (heavily contested).
    Derived from positioning and balance axes.
    """
    # Positioning contribution: how close is the defender?
    pos_contest = {
        DefenderPositioning.LOCKED_UP: 0.85,
        DefenderPositioning.TRAILING: 0.55,
        DefenderPositioning.HALF_STEP_BEHIND: 0.35,
        DefenderPositioning.BEATEN: 0.15,
        DefenderPositioning.BLOWN_BY: 0.0,
    }[matchup.positioning]

    # Balance contribution: can the defender actually contest?
    bal_factor = {
        DefenderBalance.SET: 1.0,
        DefenderBalance.SHIFTING: 0.8,
        DefenderBalance.OFF_BALANCE: 0.5,
        DefenderBalance.STUMBLING: 0.2,
        DefenderBalance.ON_FLOOR: 0.0,
    }[matchup.balance]

    # Effective contest = position-based contest * balance factor
    # A LOCKED_UP defender who is OFF_BALANCE contests at 0.85 * 0.5 = 0.425
    return pos_contest * bal_factor
