"""Tests for the game engine and game loop."""

import random

from basketball_sim.core.engine import GameEngine
from basketball_sim.core.event_bus import EventBus
from basketball_sim.core.pipeline import ModifierPipeline
from basketball_sim.core.types import (
    EventType,
    GameEvent,
    GameState,
    Player,
    RulesConfig,
    TeamState,
)


def _make_team(team_id: str, name: str) -> TeamState:
    """Create a team with 5 basic players."""
    players = []
    positions = ["PG", "SG", "SF", "PF", "C"]
    for i, pos in enumerate(positions):
        p = Player(
            player_id=f"{team_id}_p{i}",
            display_name=f"{name} Player {i}",
            team_id=team_id,
            position=pos,
        )
        players.append(p)

    return TeamState(
        team_id=team_id,
        name=name,
        players=players,
        on_court=[p.player_id for p in players],
    )


def _make_game(seed: int = 42) -> GameState:
    """Create a game state with two teams."""
    return GameState(
        home_team=_make_team("home", "Home Team"),
        away_team=_make_team("away", "Away Team"),
        possession_team_id="home",
        rng=random.Random(seed),
    )


def test_engine_runs_to_completion():
    bus = EventBus()
    pipeline = ModifierPipeline()
    engine = GameEngine(event_bus=bus, pipeline=pipeline)

    game = _make_game()
    result = engine.simulate_game(game)

    # Game should complete all 4 quarters
    assert result.quarter == 4
    assert result.game_clock == 0.0

    # Should have scored some points (stub resolver is 45% make rate)
    total = result.score["home"] + result.score["away"]
    assert total > 0

    # Should have some possessions and actions
    assert engine.stats.possessions_simulated > 0
    assert engine.stats.actions_resolved > 0


def test_deterministic_with_same_seed():
    """Same seed = same game, every time."""
    scores = []
    for _ in range(3):
        bus = EventBus()
        pipeline = ModifierPipeline()
        engine = GameEngine(event_bus=bus, pipeline=pipeline)
        game = _make_game(seed=12345)
        result = engine.simulate_game(game)
        scores.append((result.score["home"], result.score["away"]))

    # All three runs should produce identical scores
    assert scores[0] == scores[1] == scores[2]


def test_different_seeds_different_results():
    """Different seeds should (almost certainly) produce different games."""
    results = []
    for seed in [1, 2, 3]:
        bus = EventBus()
        pipeline = ModifierPipeline()
        engine = GameEngine(event_bus=bus, pipeline=pipeline)
        game = _make_game(seed=seed)
        result = engine.simulate_game(game)
        results.append(result.score["home"])

    # Extremely unlikely all three are identical with different seeds
    assert len(set(results)) > 1


def test_events_emitted():
    """The engine should emit game lifecycle events."""
    bus = EventBus()
    pipeline = ModifierPipeline()
    engine = GameEngine(event_bus=bus, pipeline=pipeline)

    game = _make_game()
    engine.simulate_game(game)

    event_types = [e.event_type for e in bus.history]

    assert EventType.GAME_START in event_types
    assert EventType.GAME_END in event_types
    assert EventType.QUARTER_START in event_types
    assert EventType.QUARTER_END in event_types
    assert EventType.POSSESSION_START in event_types
    assert EventType.POSSESSION_END in event_types
    assert EventType.SHOT_ATTEMPT in event_types


def test_custom_rules():
    """Engine respects custom rules config."""
    bus = EventBus()
    pipeline = ModifierPipeline()
    # Very short quarters = fewer possessions
    rules = RulesConfig(quarter_length=30.0, shot_clock=10.0)
    engine = GameEngine(event_bus=bus, pipeline=pipeline, rules=rules)

    game = _make_game()
    result = engine.simulate_game(game)

    # With 30-second quarters (4 quarters = 2 min total),
    # there should be relatively few possessions
    assert engine.stats.possessions_simulated < 50


def test_event_subscribers_receive_during_game():
    """External subscribers get events in real time, not just from history."""
    bus = EventBus()
    pipeline = ModifierPipeline()
    engine = GameEngine(event_bus=bus, pipeline=pipeline)

    shots_made = []
    bus.subscribe(EventType.SHOT_MADE, lambda e: shots_made.append(e))

    game = _make_game()
    engine.simulate_game(game)

    # Should have received some made shots via the subscriber
    assert len(shots_made) > 0
    assert all(e.event_type == EventType.SHOT_MADE for e in shots_made)


def test_profiling_stats():
    bus = EventBus()
    pipeline = ModifierPipeline()
    engine = GameEngine(event_bus=bus, pipeline=pipeline)

    game = _make_game()
    engine.simulate_game(game)

    assert engine.stats.total_time_seconds > 0
    assert engine.stats.avg_time_per_possession > 0
    assert len(engine.stats.possession_times) == engine.stats.possessions_simulated
