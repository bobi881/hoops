"""History modifier -- this-game matchup history and scouting.

Tracks what moves the ball handler has used against this defender
during the current game. If the same move is used repeatedly, the
defender starts to anticipate it. Variety is rewarded.
"""

from __future__ import annotations

from collections import Counter

from basketball_sim.core.types import ActionContext, ActionType, Modifier

# Module-level game history tracker. Reset between games.
# Maps (attacker_id, defender_id) -> list of move_ids used
_game_history: dict[tuple[str, str], list[str]] = {}


def reset_history() -> None:
    """Clear game history. Call at the start of each game."""
    _game_history.clear()


def record_action(attacker_id: str, defender_id: str, move_id: str) -> None:
    """Record that a move was used in this matchup."""
    key = (attacker_id, defender_id)
    if key not in _game_history:
        _game_history[key] = []
    _game_history[key].append(move_id)


def history_modifier(context: ActionContext) -> Modifier:
    """Compute modifier based on this-game matchup history.

    Repeated moves become less effective as the defender learns.
    Using a new move gets a novelty bonus.
    """
    action = context.action
    if action.action_type != ActionType.DRIBBLE_MOVE:
        return Modifier()

    move_id = action.data.get("move", "")
    if not move_id:
        return Modifier()

    attacker_id = context.attacker.player_id
    defender_id = context.defender.player_id
    key = (attacker_id, defender_id)

    history = _game_history.get(key, [])
    if not history:
        return Modifier()

    counts = Counter(history)
    total_moves = len(history)
    this_move_count = counts.get(move_id, 0)

    tags: list[str] = []

    # --- Repetition penalty ---
    # First use: no penalty. Each repeat makes it less effective.
    # Diminishing returns: 1st repeat = -0.04, 2nd = -0.03, 3rd = -0.02, etc.
    if this_move_count == 0:
        # Novelty bonus for a move not yet seen
        positioning_boost = 0.04
        balance_boost = 0.02
        tags.append("new_look")
    else:
        # Penalty increases with repetition but caps out
        penalty_per_use = max(0.01, 0.05 - this_move_count * 0.01)
        total_penalty = min(0.12, this_move_count * penalty_per_use)
        positioning_boost = -total_penalty
        balance_boost = -total_penalty * 0.5

        if this_move_count >= 3:
            tags.append("defender_reading_it")
        elif this_move_count >= 2:
            tags.append("defender_adjusting")

    # --- Variety bonus ---
    # If the attacker has used many different moves, they're harder to read
    unique_moves = len(counts)
    if unique_moves >= 4 and total_moves >= 6:
        positioning_boost += 0.03
        tags.append("unpredictable")
    elif unique_moves == 1 and total_moves >= 3:
        positioning_boost -= 0.03
        tags.append("one_dimensional")

    # --- Defender basketball IQ factor ---
    def_iq = context.defender.attributes.basketball_iq / 100.0
    # Smart defenders learn faster
    positioning_boost *= (0.7 + def_iq * 0.6)  # 0.7x to 1.3x
    balance_boost *= (0.7 + def_iq * 0.6)

    # Record this action for future reference
    record_action(attacker_id, defender_id, move_id)

    return Modifier(
        positioning_boost=positioning_boost,
        balance_boost=balance_boost,
        tags=tags,
    )
