"""Tests for the modifier pipeline."""

import random

from basketball_sim.core.pipeline import ModifierPipeline
from basketball_sim.core.types import (
    Action,
    ActionContext,
    ActionType,
    GameState,
    MatchupState,
    Modifier,
    Player,
    PossessionState,
    PlayerOnCourt,
    TeamState,
)


def _make_context() -> ActionContext:
    """Helper: build a minimal ActionContext for testing."""
    player = Player(player_id="p1", display_name="Test", team_id="t1", position="PG")
    defender = Player(player_id="p2", display_name="Def", team_id="t2", position="SG")
    possession = PossessionState(
        ball_handler=PlayerOnCourt(player=player, cell="D6"),
        offensive_team_id="t1",
        defensive_team_id="t2",
    )
    game = GameState(
        home_team=TeamState(team_id="t1", name="Home"),
        away_team=TeamState(team_id="t2", name="Away"),
    )
    return ActionContext(
        action=Action(action_type=ActionType.DRIBBLE_MOVE, player_id="p1"),
        attacker=player,
        defender=defender,
        matchup=MatchupState(),
        possession=possession,
        game_state=game,
        rng=random.Random(42),
        cell="D6",
    )


def test_empty_pipeline():
    pipeline = ModifierPipeline()
    ctx = _make_context()
    agg = pipeline.apply(ctx)
    assert agg.positioning_boost == 0.0
    assert agg.tags == []


def test_single_modifier():
    pipeline = ModifierPipeline()

    def fatigue_mod(ctx: ActionContext) -> Modifier:
        return Modifier(positioning_boost=-0.05, tags=["tired"])

    pipeline.register(fatigue_mod)
    agg = pipeline.apply(_make_context())

    assert abs(agg.positioning_boost - (-0.05)) < 1e-9
    assert agg.tags == ["tired"]


def test_multiple_modifiers_combine():
    pipeline = ModifierPipeline()

    pipeline.register(lambda ctx: Modifier(positioning_boost=0.05, tags=["a"]))
    pipeline.register(lambda ctx: Modifier(positioning_boost=0.03, tags=["b"]))
    pipeline.register(lambda ctx: Modifier(balance_boost=-0.02, tags=["c"]))

    agg = pipeline.apply(_make_context())

    assert abs(agg.positioning_boost - 0.08) < 1e-9
    assert abs(agg.balance_boost - (-0.02)) < 1e-9
    assert set(agg.tags) == {"a", "b", "c"}


def test_pipeline_clamps():
    pipeline = ModifierPipeline()

    # 10 modifiers each adding 0.10 = total 1.0, should be clamped to 0.25
    for _ in range(10):
        pipeline.register(lambda ctx: Modifier(positioning_boost=0.10))

    agg = pipeline.apply(_make_context())
    assert agg.positioning_boost == 0.25


def test_failing_modifier_returns_neutral():
    pipeline = ModifierPipeline()

    def bad_mod(ctx: ActionContext) -> Modifier:
        raise RuntimeError("boom")

    def good_mod(ctx: ActionContext) -> Modifier:
        return Modifier(positioning_boost=0.05, tags=["good"])

    pipeline.register(bad_mod, name="bad")
    pipeline.register(good_mod, name="good")

    agg = pipeline.apply(_make_context())

    # Bad modifier was skipped, good modifier applied
    assert abs(agg.positioning_boost - 0.05) < 1e-9
    assert agg.tags == ["good"]


def test_modifier_disabled_after_max_failures():
    pipeline = ModifierPipeline()

    call_count = 0

    def bad_mod(ctx: ActionContext) -> Modifier:
        nonlocal call_count
        call_count += 1
        raise RuntimeError("always fails")

    pipeline.register(bad_mod, name="bad")

    # Run more than MAX_FAILURES times
    for _ in range(15):
        pipeline.apply(_make_context())

    # After 10 failures, the modifier should be disabled
    assert "bad" in pipeline.disabled_modifiers
    # It should have been called exactly 10 times (disabled after 10th failure)
    assert call_count == 10


def test_unregister():
    pipeline = ModifierPipeline()
    pipeline.register(lambda ctx: Modifier(positioning_boost=0.05), name="mod_a")
    pipeline.register(lambda ctx: Modifier(positioning_boost=0.03), name="mod_b")

    assert len(pipeline) == 2
    pipeline.unregister("mod_a")
    assert len(pipeline) == 1
    assert "mod_b" in pipeline.modifier_names


def test_reset():
    pipeline = ModifierPipeline()

    def bad_mod(ctx: ActionContext) -> Modifier:
        raise RuntimeError("fail")

    pipeline.register(bad_mod, name="bad")

    for _ in range(10):
        pipeline.apply(_make_context())

    assert "bad" in pipeline.disabled_modifiers

    pipeline.reset()
    assert len(pipeline.disabled_modifiers) == 0
