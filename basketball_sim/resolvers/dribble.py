"""Dribble move resolver -- multi-axis state transitions.

Takes a dribble move action, looks up the move data, applies modifier
boosts + cross-axis boosts, rolls each axis independently, generates tags.
"""

from __future__ import annotations

from basketball_sim.core.types import (
    ActionContext,
    ActionResult,
    AggregatedModifier,
    BallHandlerRhythm,
    DefenderBalance,
    DefenderPositioning,
    DefenderStance,
    EventType,
    GameEvent,
    MatchupState,
    MoveData,
)
from basketball_sim.resolvers.transitions import (
    apply_boost_to_transitions,
    get_cross_axis_boost,
    roll_transition,
)

# Favorable states for the attacker on each axis
_POS_FAVORABLE = {"TRAILING", "HALF_STEP_BEHIND", "BEATEN", "BLOWN_BY"}
_BAL_FAVORABLE = {"SHIFTING", "OFF_BALANCE", "STUMBLING", "ON_FLOOR"}
_STA_FAVORABLE = {"REACHING", "RECOVERING", "FLAILING", "IN_AIR", "CLOSING_OUT"}


def resolve_dribble(
    move: MoveData,
    matchup: MatchupState,
    agg: AggregatedModifier,
    context: ActionContext,
) -> ActionResult:
    """Resolve a dribble move through the multi-axis state machine.

    Args:
        move: The dribble move data (loaded from JSON).
        matchup: Current matchup state across all 5 axes.
        agg: Aggregated modifier from the pipeline (already clamped).
        context: Full action context including RNG.

    Returns:
        ActionResult with updated matchup, events, and tags.
    """
    rng = context.rng

    # Drain fatigue on the attacker proportional to the move's energy cost.
    # Small decrements per action accumulate over a long possession.
    if move.energy_cost > 0.0:
        atk = context.attacker
        atk.fatigue.cardiovascular = max(
            0.0, atk.fatigue.cardiovascular - move.energy_cost * 0.8
        )
        atk.fatigue.muscular = max(
            0.0, atk.fatigue.muscular - move.energy_cost * 0.6
        )
        atk.fatigue.mental = max(
            0.0, atk.fatigue.mental - move.energy_cost * 0.3
        )

    # Cross-axis boosts from the move's JSON data
    cross = get_cross_axis_boost(
        move.cross_axis_boosts,
        current_balance=matchup.balance.name,
        current_stance=matchup.stance.name,
        current_positioning=matchup.positioning.name,
    )

    # --- Resolve positioning axis ---
    pos_key = f"from_{matchup.positioning.name}"
    pos_transitions = move.transitions.get("positioning", {}).get(pos_key, {})
    if pos_transitions:
        adjusted_pos = apply_boost_to_transitions(
            pos_transitions,
            boost=agg.positioning_boost + cross.get("positioning", 0.0),
            favorable=_POS_FAVORABLE,
        )
        new_pos_name = roll_transition(adjusted_pos, rng)
        new_positioning = DefenderPositioning[new_pos_name]
    else:
        new_positioning = matchup.positioning

    # --- Resolve balance axis ---
    bal_key = f"from_{matchup.balance.name}"
    bal_transitions = move.transitions.get("balance", {}).get(bal_key, {})
    if bal_transitions:
        adjusted_bal = apply_boost_to_transitions(
            bal_transitions,
            boost=agg.balance_boost + cross.get("balance", 0.0),
            favorable=_BAL_FAVORABLE,
        )
        new_bal_name = roll_transition(adjusted_bal, rng)
        new_balance = DefenderBalance[new_bal_name]
    else:
        new_balance = matchup.balance

    # --- Resolve stance axis ---
    sta_key = f"from_{matchup.stance.name}"
    sta_transitions = move.transitions.get("stance", {}).get(sta_key, {})
    if sta_transitions:
        adjusted_sta = apply_boost_to_transitions(
            sta_transitions,
            boost=agg.stance_boost + cross.get("stance", 0.0),
            favorable=_STA_FAVORABLE,
        )
        new_sta_name = roll_transition(adjusted_sta, rng)
        new_stance = DefenderStance[new_sta_name]
    else:
        new_stance = matchup.stance

    # --- Rhythm axis (simplified: attacking after a successful move) ---
    pos_improved = _pos_order(new_positioning) > _pos_order(matchup.positioning)
    bal_degraded = _bal_order(new_balance) > _bal_order(matchup.balance)

    if pos_improved or bal_degraded:
        # Success: escalate rhythm
        new_rhythm = _advance_rhythm(matchup.rhythm)
    else:
        new_rhythm = matchup.rhythm

    # --- Generate tags ---
    tags: list[str] = list(agg.tags)

    # Success tags: any axis improved
    if pos_improved or bal_degraded:
        tags.extend(move.tags_on_success)

    # Critical tags: defender stumbling/on floor
    if new_balance in (DefenderBalance.STUMBLING, DefenderBalance.ON_FLOOR):
        tags.extend(move.tags_on_critical)

    if new_stance in (DefenderStance.FLAILING,):
        if "ankle_breaker" not in tags:
            tags.append("ankle_breaker")

    # Auto-transition: if balance is STUMBLING and stance was RECOVERING,
    # stance becomes FLAILING
    if new_balance == DefenderBalance.STUMBLING and matchup.stance == DefenderStance.RECOVERING:
        new_stance = DefenderStance.FLAILING

    new_matchup = MatchupState(
        positioning=new_positioning,
        balance=new_balance,
        stance=new_stance,
        rhythm=new_rhythm,
        help_status=matchup.help_status,  # unchanged by dribble moves
    )

    event = GameEvent(
        event_type=EventType.DRIBBLE_MOVE,
        player_id=context.action.player_id,
        data={
            "move": move.move_id,
            "from_positioning": matchup.positioning.name,
            "to_positioning": new_positioning.name,
            "from_balance": matchup.balance.name,
            "to_balance": new_balance.name,
            "from_stance": matchup.stance.name,
            "to_stance": new_stance.name,
        },
        tags=tags,
    )

    return ActionResult(
        new_matchup=new_matchup,
        events=[event],
        tags=tags,
        ends_possession=False,
    )


def _pos_order(p: DefenderPositioning) -> int:
    """Numeric ordering for positioning (higher = more advantage for attacker)."""
    return {
        DefenderPositioning.LOCKED_UP: 0,
        DefenderPositioning.TRAILING: 1,
        DefenderPositioning.HALF_STEP_BEHIND: 2,
        DefenderPositioning.BEATEN: 3,
        DefenderPositioning.BLOWN_BY: 4,
    }[p]


def _bal_order(b: DefenderBalance) -> int:
    """Numeric ordering for balance (higher = worse for defender)."""
    return {
        DefenderBalance.SET: 0,
        DefenderBalance.SHIFTING: 1,
        DefenderBalance.OFF_BALANCE: 2,
        DefenderBalance.STUMBLING: 3,
        DefenderBalance.ON_FLOOR: 4,
    }[b]


def _advance_rhythm(r: BallHandlerRhythm) -> BallHandlerRhythm:
    """Advance the ball handler's rhythm after a successful move."""
    progression = {
        BallHandlerRhythm.SURVEYING: BallHandlerRhythm.GATHERING,
        BallHandlerRhythm.GATHERING: BallHandlerRhythm.ATTACKING,
        BallHandlerRhythm.ATTACKING: BallHandlerRhythm.ATTACKING,
        BallHandlerRhythm.ELEVATED: BallHandlerRhythm.ELEVATED,
        BallHandlerRhythm.COMMITTED: BallHandlerRhythm.COMMITTED,
    }
    return progression[r]
