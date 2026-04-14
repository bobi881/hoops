"""Coaching modifier -- scheme adjustments, matchup hunting, defensive focus.

Models how coaching decisions affect individual actions. Good coaching
means better matchup exploitation, smarter defensive schemes, and
adjustments based on what's working.
"""

from __future__ import annotations

from basketball_sim.core.types import ActionContext, ActionType, Modifier

# Active coaching adjustments. Maps team_id -> dict of adjustments.
_coaching_adjustments: dict[str, dict[str, float]] = {}


def set_coaching_adjustment(team_id: str, key: str, value: float) -> None:
    """Set a coaching adjustment for a team."""
    if team_id not in _coaching_adjustments:
        _coaching_adjustments[team_id] = {}
    _coaching_adjustments[team_id][key] = value


def get_coaching_adjustment(team_id: str, key: str, default: float = 0.0) -> float:
    """Get a coaching adjustment value."""
    return _coaching_adjustments.get(team_id, {}).get(key, default)


def reset_coaching() -> None:
    """Clear all coaching adjustments."""
    _coaching_adjustments.clear()


def coaching_modifier(context: ActionContext) -> Modifier:
    """Compute modifier based on coaching adjustments and scheme.

    Coaching affects:
    - Defensive intensity/focus on specific players
    - Offensive scheme emphasis (pace, ISO frequency, etc.)
    - Matchup exploitation awareness
    """
    attacker = context.attacker
    defender = context.defender
    possession = context.possession
    action = context.action

    off_team = possession.offensive_team_id
    def_team = possession.defensive_team_id

    tags: list[str] = []
    positioning_boost = 0.0
    balance_boost = 0.0
    rhythm_boost = 0.0
    shot_boost = 0.0

    # --- Defensive focus adjustment ---
    # If the defensive coach has flagged this attacker as a focus player,
    # the defender gets a boost (penalty for attacker)
    focus_on_player = get_coaching_adjustment(
        def_team, f"focus_{attacker.player_id}", 0.0
    )
    if focus_on_player > 0:
        positioning_boost -= focus_on_player * 0.08
        balance_boost -= focus_on_player * 0.04
        tags.append("defense_keying_on_player")

    # --- Matchup hunting ---
    # If offensive coach identified a favorable matchup to exploit
    exploit_matchup = get_coaching_adjustment(
        off_team, f"exploit_{defender.player_id}", 0.0
    )
    if exploit_matchup > 0:
        positioning_boost += exploit_matchup * 0.06
        shot_boost += exploit_matchup * 0.02
        tags.append("matchup_hunting")

    # --- Offensive scheme ---
    pace = get_coaching_adjustment(off_team, "pace", 0.5)
    # High pace = more transition opportunities, slight rhythm boost
    if pace > 0.7:
        rhythm_boost += 0.02
        if possession.is_fast_break:
            positioning_boost += 0.04
            tags.append("pushing_pace")
    elif pace < 0.3:
        # Slow pace = more deliberate, better shot selection
        shot_boost += 0.01
        tags.append("grinding")

    # --- Defensive scheme intensity ---
    def_intensity = get_coaching_adjustment(def_team, "defensive_intensity", 0.5)
    if def_intensity > 0.7:
        # High intensity defense = harder for attacker
        positioning_boost -= 0.03
        shot_boost -= 0.01
        tags.append("locked_in_defense")
    elif def_intensity < 0.3:
        positioning_boost += 0.02
        tags.append("lax_defense")

    # --- Paint protection emphasis ---
    paint_protection = get_coaching_adjustment(def_team, "paint_protection", 0.5)
    cell = context.cell
    if paint_protection > 0.6:
        from basketball_sim.core.grid import COURT
        if COURT.is_valid(cell) and COURT.get(cell).is_paint:
            shot_boost -= paint_protection * 0.04
            tags.append("wall_in_the_paint")

    # --- Three-point defense emphasis ---
    three_defense = get_coaching_adjustment(def_team, "three_point_defense", 0.5)
    if action.action_type == ActionType.SHOT and "three" in action.data.get("shot_type", ""):
        if three_defense > 0.6:
            shot_boost -= three_defense * 0.03
            tags.append("closing_out_hard")

    return Modifier(
        positioning_boost=positioning_boost,
        balance_boost=balance_boost,
        rhythm_boost=rhythm_boost,
        shot_pct_boost=shot_boost,
        tags=tags,
    )
