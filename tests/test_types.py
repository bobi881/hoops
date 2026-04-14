"""Tests for core type definitions."""

from basketball_sim.core.types import (
    AggregatedModifier,
    BallHandlerRhythm,
    DefenderBalance,
    DefenderPositioning,
    DefenderStance,
    HelpDefenseStatus,
    MatchupState,
    Modifier,
    Player,
    PlayerAttributes,
)


def test_matchup_state_defaults():
    m = MatchupState()
    assert m.positioning == DefenderPositioning.LOCKED_UP
    assert m.balance == DefenderBalance.SET
    assert m.stance == DefenderStance.GUARDING
    assert m.rhythm == BallHandlerRhythm.SURVEYING
    assert m.help_status == HelpDefenseStatus.NO_HELP


def test_modifier_combine_additive():
    agg = AggregatedModifier()
    m1 = Modifier(positioning_boost=0.05, balance_boost=-0.03, tags=["fatigue"])
    m2 = Modifier(positioning_boost=0.02, balance_boost=0.08, tags=["confident"])

    agg.combine(m1)
    agg.combine(m2)

    assert abs(agg.positioning_boost - 0.07) < 1e-9
    assert abs(agg.balance_boost - 0.05) < 1e-9
    assert agg.tags == ["fatigue", "confident"]


def test_modifier_combine_is_order_independent():
    m1 = Modifier(positioning_boost=0.05, shot_pct_boost=0.02)
    m2 = Modifier(positioning_boost=-0.03, shot_pct_boost=0.01)

    agg_a = AggregatedModifier()
    agg_a.combine(m1)
    agg_a.combine(m2)

    agg_b = AggregatedModifier()
    agg_b.combine(m2)
    agg_b.combine(m1)

    assert abs(agg_a.positioning_boost - agg_b.positioning_boost) < 1e-9
    assert abs(agg_a.shot_pct_boost - agg_b.shot_pct_boost) < 1e-9


def test_modifier_clamp():
    agg = AggregatedModifier()
    # Stack a bunch of modifiers that would exceed the clamp range
    for _ in range(10):
        agg.combine(Modifier(positioning_boost=0.10, shot_pct_boost=0.05))

    agg.clamp()

    assert agg.positioning_boost == 0.25  # clamped to max
    assert agg.shot_pct_boost == 0.15  # shot_pct clamped to 0.15


def test_modifier_clamp_negative():
    agg = AggregatedModifier()
    for _ in range(10):
        agg.combine(Modifier(balance_boost=-0.10))

    agg.clamp()

    assert agg.balance_boost == -0.25  # clamped to min


def test_player_defaults():
    p = Player(player_id="test_1", display_name="Test Player", team_id="team_a", position="PG")
    assert p.attributes.ball_handling == 70
    assert p.mental.confidence == 0.5
    assert p.fatigue.cardiovascular == 1.0
    assert p.tendencies.iso_frequency == 0.3
    assert p.badges == []
    assert p.move_repertoire == []
