"""Tests for Phase 2 resolvers: dribble, shoot, pass, rebound."""

from __future__ import annotations

import random
from collections import Counter
from typing import Optional

from basketball_sim.core.types import (
    Action,
    ActionContext,
    ActionType,
    AggregatedModifier,
    BallHandlerRhythm,
    DefenderBalance,
    DefenderPositioning,
    DefenderStance,
    GameState,
    MatchupState,
    Modifier,
    OffBallState,
    Player,
    PlayerOnCourt,
    PossessionState,
    TeamState,
)
from basketball_sim.data.loader import load_moves
from basketball_sim.resolvers.dribble import resolve_dribble
from basketball_sim.resolvers.pass_action import resolve_pass
from basketball_sim.resolvers.rebound import resolve_rebound
from basketball_sim.resolvers.shoot import resolve_shot
from basketball_sim.resolvers.transitions import apply_boost_to_transitions, roll_transition


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _player(pid: str = "p1", ball_handling: int = 80, three_pt: int = 75) -> Player:
    p = Player(player_id=pid, display_name=f"Player {pid}", team_id="t1", position="PG")
    p.attributes.ball_handling = ball_handling
    p.attributes.three_point = three_pt
    p.attributes.passing_vision = 80
    p.attributes.passing_accuracy = 80
    return p


def _defender(pid: str = "d1", perimeter_def: int = 75) -> Player:
    p = Player(player_id=pid, display_name=f"Defender {pid}", team_id="t2", position="SG")
    p.attributes.perimeter_defense = perimeter_def
    return p


def _context(
    matchup: Optional[MatchupState] = None,
    cell: str = "D6",
    action_type: ActionType = ActionType.DRIBBLE_MOVE,
    seed: int = 42,
    data: Optional[dict] = None,
) -> ActionContext:
    player = _player()
    defender = _defender()
    poc = PlayerOnCourt(player=player, cell=cell, matchup=matchup or MatchupState())
    possession = PossessionState(
        ball_handler=poc,
        off_ball_offense=[
            OffBallState(player=_player("p2"), cell="B6"),
            OffBallState(player=_player("p3"), cell="F6"),
        ],
        defense=[
            PlayerOnCourt(player=_defender("d1"), cell="D6"),
            PlayerOnCourt(player=_defender("d2"), cell="B6"),
            PlayerOnCourt(player=_defender("d3"), cell="F6"),
        ],
        offensive_team_id="t1",
        defensive_team_id="t2",
    )
    game = GameState(
        home_team=TeamState(team_id="t1", name="Home"),
        away_team=TeamState(team_id="t2", name="Away"),
    )
    return ActionContext(
        action=Action(action_type=action_type, player_id="p1", data=data or {}),
        attacker=player,
        defender=defender,
        matchup=matchup or MatchupState(),
        possession=possession,
        game_state=game,
        rng=random.Random(seed),
        cell=cell,
    )


# ---------------------------------------------------------------------------
# Transition math tests
# ---------------------------------------------------------------------------

def test_apply_boost_positive():
    base = {"LOCKED_UP": 0.80, "TRAILING": 0.15, "HALF_STEP_BEHIND": 0.05}
    result = apply_boost_to_transitions(base, 0.10, ["TRAILING", "HALF_STEP_BEHIND"])

    # Favorable states should have more probability
    assert result["TRAILING"] > base["TRAILING"]
    assert result["HALF_STEP_BEHIND"] > base["HALF_STEP_BEHIND"]
    assert result["LOCKED_UP"] < base["LOCKED_UP"]

    # Should still sum to ~1.0
    total = sum(result.values())
    assert abs(total - 1.0) < 0.001


def test_apply_boost_negative():
    base = {"LOCKED_UP": 0.50, "TRAILING": 0.30, "BEATEN": 0.20}
    result = apply_boost_to_transitions(base, -0.10, ["TRAILING", "BEATEN"])

    assert result["TRAILING"] < base["TRAILING"]
    assert result["LOCKED_UP"] > base["LOCKED_UP"]
    total = sum(result.values())
    assert abs(total - 1.0) < 0.001


def test_apply_boost_zero():
    base = {"A": 0.6, "B": 0.4}
    result = apply_boost_to_transitions(base, 0.0, ["B"])
    assert abs(result["A"] - 0.6) < 0.001
    assert abs(result["B"] - 0.4) < 0.001


def test_apply_boost_no_negative_probs():
    base = {"LOCKED_UP": 0.95, "TRAILING": 0.05}
    # Huge negative boost shouldn't produce negative probabilities
    result = apply_boost_to_transitions(base, -0.25, ["TRAILING"])
    assert all(v >= 0 for v in result.values())
    total = sum(result.values())
    assert abs(total - 1.0) < 0.001


def test_roll_transition_deterministic():
    transitions = {"A": 0.5, "B": 0.3, "C": 0.2}
    rng = random.Random(42)
    result = roll_transition(transitions, rng)
    assert result in ("A", "B", "C")

    # Same seed = same result
    rng2 = random.Random(42)
    result2 = roll_transition(transitions, rng2)
    assert result == result2


def test_roll_transition_distribution():
    """Over many rolls, the distribution should approximate the weights."""
    transitions = {"A": 0.6, "B": 0.3, "C": 0.1}
    rng = random.Random(123)
    counts = Counter(roll_transition(transitions, rng) for _ in range(10000))

    assert 0.55 < counts["A"] / 10000 < 0.65
    assert 0.25 < counts["B"] / 10000 < 0.35
    assert 0.06 < counts["C"] / 10000 < 0.14


# ---------------------------------------------------------------------------
# Data loader tests
# ---------------------------------------------------------------------------

def test_load_moves_from_default_dir():
    moves = load_moves()
    assert len(moves) >= 6  # we defined 6 moves in JSON
    assert "crossover" in moves
    assert "hesitation" in moves
    assert "jab_step" in moves
    assert "behind_the_back" in moves
    assert "step_back" in moves
    assert "spin_move" in moves


def test_move_data_structure():
    moves = load_moves()
    crossover = moves["crossover"]
    assert crossover.display_name == "Crossover"
    assert crossover.category == "crossover"
    assert "positioning" in crossover.transitions
    assert "balance" in crossover.transitions
    assert "crossover" in crossover.tags_on_success
    assert crossover.energy_cost == 0.04
    assert crossover.required_attributes["ball_handling"] == 60


# ---------------------------------------------------------------------------
# Dribble resolver tests
# ---------------------------------------------------------------------------

def test_dribble_resolver_returns_result():
    moves = load_moves()
    crossover = moves["crossover"]
    ctx = _context()
    agg = AggregatedModifier()

    result = resolve_dribble(crossover, ctx.matchup, agg, ctx)

    assert result.new_matchup is not None
    assert len(result.events) == 1
    assert result.events[0].event_type.name == "DRIBBLE_MOVE"
    assert not result.ends_possession


def test_dribble_resolver_deterministic():
    moves = load_moves()
    crossover = moves["crossover"]
    agg = AggregatedModifier()

    results = []
    for _ in range(3):
        ctx = _context(seed=999)
        r = resolve_dribble(crossover, ctx.matchup, agg, ctx)
        results.append(r.new_matchup.positioning.name)

    assert results[0] == results[1] == results[2]


def test_dribble_resolver_boost_shifts_outcomes():
    """Positive positioning boost should produce more favorable outcomes."""
    moves = load_moves()
    crossover = moves["crossover"]

    no_boost_outcomes = Counter()
    boosted_outcomes = Counter()

    for seed in range(1000):
        ctx = _context(seed=seed)
        r = resolve_dribble(crossover, ctx.matchup, AggregatedModifier(), ctx)
        no_boost_outcomes[r.new_matchup.positioning.name] += 1

        ctx2 = _context(seed=seed)
        agg = AggregatedModifier(positioning_boost=0.20)
        r2 = resolve_dribble(crossover, ctx2.matchup, agg, ctx2)
        boosted_outcomes[r2.new_matchup.positioning.name] += 1

    # With a +0.20 boost, we should see more TRAILING/HALF_STEP outcomes
    no_locked = no_boost_outcomes.get("LOCKED_UP", 0)
    boosted_locked = boosted_outcomes.get("LOCKED_UP", 0)
    assert boosted_locked < no_locked  # fewer LOCKED_UP with boost


def test_dribble_cross_axis_boost():
    """When defender is OFF_BALANCE, positioning should get a cross-axis bonus."""
    moves = load_moves()
    crossover = moves["crossover"]

    set_outcomes = Counter()
    offbal_outcomes = Counter()

    for seed in range(1000):
        # Defender SET
        matchup_set = MatchupState(balance=DefenderBalance.SET)
        ctx = _context(matchup=matchup_set, seed=seed)
        r = resolve_dribble(crossover, matchup_set, AggregatedModifier(), ctx)
        set_outcomes[r.new_matchup.positioning.name] += 1

        # Defender OFF_BALANCE (should get cross-axis boost to positioning)
        matchup_off = MatchupState(balance=DefenderBalance.OFF_BALANCE)
        ctx2 = _context(matchup=matchup_off, seed=seed)
        r2 = resolve_dribble(crossover, matchup_off, AggregatedModifier(), ctx2)
        offbal_outcomes[r2.new_matchup.positioning.name] += 1

    # More favorable positioning outcomes when defender is off balance
    set_favorable = sum(v for k, v in set_outcomes.items() if k != "LOCKED_UP")
    offbal_favorable = sum(v for k, v in offbal_outcomes.items() if k != "LOCKED_UP")
    assert offbal_favorable > set_favorable


def test_dribble_tags_on_success():
    """When positioning improves, success tags should be present."""
    moves = load_moves()
    crossover = moves["crossover"]

    # Run many times to find at least one success
    found_success = False
    for seed in range(200):
        ctx = _context(seed=seed)
        r = resolve_dribble(crossover, ctx.matchup, AggregatedModifier(), ctx)
        if r.new_matchup.positioning != DefenderPositioning.LOCKED_UP:
            assert "crossover" in r.tags
            assert "direction_switch" in r.tags
            found_success = True
            break

    assert found_success, "Should find at least one successful crossover in 200 attempts"


# ---------------------------------------------------------------------------
# Shot resolver tests
# ---------------------------------------------------------------------------

def test_shot_resolver_returns_result():
    ctx = _context(
        action_type=ActionType.SHOT,
        data={"shot_type": "mid_range"},
    )
    agg = AggregatedModifier()
    result = resolve_shot(ctx.matchup, agg, ctx)

    assert result.ends_possession
    assert len(result.events) == 2  # attempt + made/missed
    assert result.events[0].event_type.name == "SHOT_ATTEMPT"


def test_shot_open_vs_contested():
    """Open shots should have higher make rate than contested."""
    open_makes = 0
    contested_makes = 0

    for seed in range(2000):
        # Open: defender is BLOWN_BY + ON_FLOOR
        open_matchup = MatchupState(
            positioning=DefenderPositioning.BLOWN_BY,
            balance=DefenderBalance.ON_FLOOR,
        )
        ctx = _context(matchup=open_matchup, action_type=ActionType.SHOT,
                       data={"shot_type": "mid_range"}, seed=seed)
        r = resolve_shot(open_matchup, AggregatedModifier(), ctx)
        if r.score_change > 0:
            open_makes += 1

        # Contested: defender is LOCKED_UP + SET
        locked_matchup = MatchupState()
        ctx2 = _context(matchup=locked_matchup, action_type=ActionType.SHOT,
                        data={"shot_type": "mid_range"}, seed=seed)
        r2 = resolve_shot(locked_matchup, AggregatedModifier(), ctx2)
        if r2.score_change > 0:
            contested_makes += 1

    assert open_makes > contested_makes


def test_shot_three_pointer_value():
    ctx = _context(
        action_type=ActionType.SHOT,
        data={"shot_type": "corner_three"},
        cell="A5",  # corner three cell
    )
    result = resolve_shot(ctx.matchup, AggregatedModifier(), ctx)
    # If made, should be 3 points
    if result.score_change > 0:
        assert result.score_change == 3


# ---------------------------------------------------------------------------
# Pass resolver tests
# ---------------------------------------------------------------------------

def test_pass_resolver_short_pass():
    ctx = _context(
        action_type=ActionType.PASS,
        data={"target_id": "p2", "target_cell": "C6"},
        cell="D6",
    )
    agg = AggregatedModifier()
    result = resolve_pass(ctx.matchup, agg, ctx)

    # Short pass (1 cell) should almost always succeed
    assert len(result.events) >= 1


def test_pass_resolver_long_pass_riskier():
    """Longer passes should have higher turnover rate."""
    short_turnovers = 0
    long_turnovers = 0

    for seed in range(1000):
        # Short pass: D6 -> C6 (1 cell)
        ctx_short = _context(
            action_type=ActionType.PASS,
            data={"target_id": "p2", "target_cell": "C6"},
            cell="D6", seed=seed,
        )
        r_short = resolve_pass(ctx_short.matchup, AggregatedModifier(), ctx_short)
        if r_short.ends_possession:
            short_turnovers += 1

        # Long pass: D6 -> A3 (6 cells)
        ctx_long = _context(
            action_type=ActionType.PASS,
            data={"target_id": "p3", "target_cell": "A3"},
            cell="D6", seed=seed,
        )
        r_long = resolve_pass(ctx_long.matchup, AggregatedModifier(), ctx_long)
        if r_long.ends_possession:
            long_turnovers += 1

    assert long_turnovers > short_turnovers


# ---------------------------------------------------------------------------
# Rebound resolver tests
# ---------------------------------------------------------------------------

def test_rebound_resolver_returns_result():
    ctx = _context()
    result = resolve_rebound(ctx.possession, ctx.rng)

    assert len(result.events) == 1
    assert result.events[0].event_type.name == "REBOUND"
    assert "offensive_rebound" in result.tags or "defensive_rebound" in result.tags


def test_rebound_mostly_defensive():
    """Defensive rebounds should happen more often than offensive."""
    off_count = 0
    for seed in range(1000):
        ctx = _context(seed=seed)
        result = resolve_rebound(ctx.possession, ctx.rng)
        if "offensive_rebound" in result.tags:
            off_count += 1

    # NBA average is ~25% offensive rebound rate
    assert 0.10 < off_count / 1000 < 0.40
