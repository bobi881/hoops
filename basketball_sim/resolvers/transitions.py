"""State transition math -- the core of the multi-axis resolver.

This module handles the probability redistribution when modifiers
adjust transition tables, and the actual dice rolling.
"""

from __future__ import annotations

import random
from typing import Sequence


def apply_boost_to_transitions(
    base: dict[str, float],
    boost: float,
    favorable: Sequence[str],
) -> dict[str, float]:
    """Redistribute probability between favorable and unfavorable states.

    Args:
        base: Transition probabilities keyed by target state name.
              Must sum to ~1.0.
        boost: Additive shift. Positive = more probability flows to
               favorable states. Negative = flows back to unfavorable.
               Already clamped by the pipeline to [-0.25, 0.25].
        favorable: State names considered favorable for the attacker.

    Returns:
        Adjusted transition probabilities, normalized to sum to 1.0.
        No individual probability goes below 0.
    """
    if not base:
        return base

    fav_set = set(favorable)
    fav_total = sum(v for k, v in base.items() if k in fav_set)
    unfav_states = [k for k in base if k not in fav_set]
    unfav_total = sum(base[k] for k in unfav_states)

    if boost == 0.0 or (boost > 0 and unfav_total == 0) or (boost < 0 and fav_total == 0):
        return dict(base)

    result: dict[str, float] = {}

    for state, prob in base.items():
        if state in fav_set:
            # Distribute boost proportionally among favorable states
            share = prob / fav_total if fav_total > 0 else 1.0 / max(1, len([k for k in base if k in fav_set]))
            result[state] = max(0.0, prob + boost * share)
        else:
            # Remove from unfavorable states proportionally
            share = prob / unfav_total if unfav_total > 0 else 1.0 / max(1, len(unfav_states))
            result[state] = max(0.0, prob - boost * share)

    # Renormalize
    total = sum(result.values())
    if total > 0:
        result = {k: v / total for k, v in result.items()}
    return result


def roll_transition(transitions: dict[str, float], rng: random.Random) -> str:
    """Roll a weighted random choice from transition probabilities.

    Args:
        transitions: State name -> probability. Must sum to ~1.0.
        rng: Seeded random instance.

    Returns:
        The chosen state name.
    """
    states = list(transitions.keys())
    weights = list(transitions.values())
    return rng.choices(states, weights=weights, k=1)[0]


def get_cross_axis_boost(
    move_cross_boosts: dict[str, float],
    current_balance: str,
    current_stance: str,
    current_positioning: str,
) -> dict[str, float]:
    """Calculate cross-axis boost values from the move's JSON data.

    Cross-axis boosts encode things like "if the defender is OFF_BALANCE,
    positioning transitions get a bonus." The keys in move_cross_boosts
    follow the pattern: '{axis}_{state}_boosts_{target_axis}'.

    Returns:
        Dict mapping axis name to additional boost value.
    """
    boosts: dict[str, float] = {
        "positioning": 0.0,
        "balance": 0.0,
        "stance": 0.0,
    }

    for key, value in move_cross_boosts.items():
        # Parse keys like "balance_OFF_BALANCE_boosts_positioning"
        parts = key.split("_boosts_")
        if len(parts) != 2:
            continue
        source_part, target_axis = parts
        # source_part is like "balance_OFF_BALANCE"
        # Check if the current state matches
        if f"balance_{current_balance}" == source_part:
            boosts[target_axis] = boosts.get(target_axis, 0.0) + value
        elif f"stance_{current_stance}" == source_part:
            boosts[target_axis] = boosts.get(target_axis, 0.0) + value
        elif f"positioning_{current_positioning}" == source_part:
            boosts[target_axis] = boosts.get(target_axis, 0.0) + value

    return boosts
