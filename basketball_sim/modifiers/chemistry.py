"""Chemistry modifier -- pairwise player chemistry, system fit, trust.

Models how well players work together. Good chemistry = better passing
lanes, better screens, better help defense rotations. System fit
affects how comfortable a player is running the team's schemes.
"""

from __future__ import annotations

from basketball_sim.core.types import ActionContext, ActionType, Modifier

# Chemistry ratings between player pairs. Maps (player_a, player_b) -> rating.
# Rating is 0.0 (terrible chemistry) to 1.0 (perfect chemistry).
# Default is 0.5 (neutral).
_chemistry_ratings: dict[tuple[str, str], float] = {}


def set_chemistry(player_a: str, player_b: str, rating: float) -> None:
    """Set pairwise chemistry between two players (symmetric)."""
    clamped = max(0.0, min(1.0, rating))
    _chemistry_ratings[(player_a, player_b)] = clamped
    _chemistry_ratings[(player_b, player_a)] = clamped


def get_chemistry(player_a: str, player_b: str) -> float:
    """Get pairwise chemistry between two players. Default 0.5."""
    return _chemistry_ratings.get((player_a, player_b), 0.5)


def reset_chemistry() -> None:
    """Clear all chemistry ratings."""
    _chemistry_ratings.clear()


def chemistry_modifier(context: ActionContext) -> Modifier:
    """Compute modifier based on team chemistry and system fit.

    For passes, chemistry between passer and receiver matters most.
    For other actions, average chemistry with on-court teammates matters.
    """
    attacker = context.attacker
    possession = context.possession
    action = context.action

    tags: list[str] = []
    positioning_boost = 0.0
    balance_boost = 0.0
    rhythm_boost = 0.0
    shot_boost = 0.0

    # --- Pairwise chemistry for passes ---
    if action.action_type == ActionType.PASS:
        target_id = action.data.get("target_id", "")
        if target_id:
            chem = get_chemistry(attacker.player_id, target_id)
            chem_effect = (chem - 0.5) * 0.12  # -0.06 to +0.06

            # Good chemistry = better passes, fewer turnovers
            positioning_boost += chem_effect
            rhythm_boost += chem_effect * 0.5

            if chem > 0.8:
                tags.append("great_chemistry")
            elif chem < 0.25:
                tags.append("poor_chemistry")

    # --- Team chemistry average (for non-pass actions) ---
    teammate_ids = [obs.player.player_id for obs in possession.off_ball_offense]
    if teammate_ids:
        avg_chem = sum(
            get_chemistry(attacker.player_id, tid) for tid in teammate_ids
        ) / len(teammate_ids)

        team_effect = (avg_chem - 0.5) * 0.06  # -0.03 to +0.03

        # Good team chemistry = better spacing, better off-ball movement
        positioning_boost += team_effect * 0.5
        rhythm_boost += team_effect

        if avg_chem > 0.75:
            tags.append("team_in_sync")
        elif avg_chem < 0.3:
            tags.append("team_disconnected")

    # --- System fit ---
    # Basketball IQ as a proxy for system fit (higher IQ = better fit)
    iq = attacker.attributes.basketball_iq / 100.0
    system_effect = (iq - 0.7) * 0.04  # slight bonus for high IQ players

    rhythm_boost += system_effect
    if iq > 0.85:
        tags.append("system_player")

    return Modifier(
        positioning_boost=positioning_boost,
        balance_boost=balance_boost,
        rhythm_boost=rhythm_boost,
        shot_pct_boost=shot_boost,
        tags=tags,
    )
