"""End-to-end integration tests wiring the real AI + real resolver.

These guard against regressions in the integration layer that unit tests
miss: ball-handler movement, shot-clock updates, rebound routing,
turnover emission on shot-clock violations, assist windowing, and
"plausibility" bounds on aggregate game stats.
"""

from __future__ import annotations

import random

import pytest

from basketball_sim.__main__ import build_sample_teams
from basketball_sim.ai.defensive_ai import BasicDefensiveAI
from basketball_sim.ai.offensive_ai import BasicOffensiveAI
from basketball_sim.core.engine import GameEngine
from basketball_sim.core.event_bus import EventBus
from basketball_sim.core.pipeline import ModifierPipeline
from basketball_sim.core.types import EventType, GameState, RulesConfig
from basketball_sim.data.loader import load_moves
from basketball_sim.modifiers.chemistry import chemistry_modifier, reset_chemistry
from basketball_sim.modifiers.coaching import coaching_modifier, reset_coaching
from basketball_sim.modifiers.fatigue import fatigue_modifier
from basketball_sim.modifiers.history import history_modifier, reset_history
from basketball_sim.modifiers.psychology import psychology_modifier
from basketball_sim.modifiers.situational import situational_modifier
from basketball_sim.modifiers.tendencies import tendencies_modifier
from basketball_sim.narration.stats_tracker import StatsTracker
from basketball_sim.resolvers.composite import CompositeResolver


def _simulate_game(seed: int = 7, quarters: int = 4, quarter_length: float = 720.0):
    """Simulate a full game with the real AI + CompositeResolver wiring."""
    home, away = build_sample_teams()

    bus = EventBus()
    stats = StatsTracker()
    stats.register_team("home", home.name)
    stats.register_team("away", away.name)
    for p in home.players:
        stats.register_player(p.player_id, "home", p.display_name)
    for p in away.players:
        stats.register_player(p.player_id, "away", p.display_name)
    bus.subscribe_all(stats.handle_event)

    pipeline = ModifierPipeline()
    for fn, name in (
        (fatigue_modifier, "fatigue"),
        (psychology_modifier, "psychology"),
        (tendencies_modifier, "tendencies"),
        (history_modifier, "history"),
        (situational_modifier, "situational"),
        (chemistry_modifier, "chemistry"),
        (coaching_modifier, "coaching"),
    ):
        pipeline.register(fn, name)

    reset_history()
    reset_chemistry()
    reset_coaching()

    moves = load_moves()
    off_ai = BasicOffensiveAI(move_registry=moves)
    def_ai = BasicDefensiveAI()
    resolver = CompositeResolver(pipeline=pipeline, move_registry=moves)

    rules = RulesConfig(quarter_length=quarter_length, num_quarters=quarters)
    engine = GameEngine(
        event_bus=bus,
        pipeline=pipeline,
        offensive_ai=off_ai,
        defensive_ai=def_ai,
        resolver=resolver,
        rules=rules,
    )

    game = GameState(
        home_team=home,
        away_team=away,
        possession_team_id="home",
        rng=random.Random(seed),
    )
    engine.simulate_game(game)

    event_counts: dict[str, int] = {}
    for event in bus.history:
        event_counts[event.event_type.name] = event_counts.get(event.event_type.name, 0) + 1

    return {
        "game": game,
        "bus": bus,
        "stats": stats,
        "engine": engine,
        "event_counts": event_counts,
        "home": home,
        "away": away,
    }


class TestPlausibility:
    """A simulated 4-quarter game must produce roughly believable stats."""

    def test_final_score_agrees_with_stats_tracker(self):
        run = _simulate_game(seed=7)
        game = run["game"]
        stats = run["stats"]

        ts_home = stats.get_team_stats("home")
        ts_away = stats.get_team_stats("away")
        assert ts_home is not None
        assert ts_away is not None

        player_home = sum(p.points for p in ts_home.players.values())
        player_away = sum(p.points for p in ts_away.players.values())
        assert game.score["home"] == player_home
        assert game.score["away"] == player_away

    def test_rebound_events_fire(self):
        run = _simulate_game(seed=7)
        assert run["event_counts"].get("REBOUND", 0) > 10, (
            f"Expected many REBOUND events, got {run['event_counts'].get('REBOUND', 0)}"
        )

    def test_shot_attempts_are_plausible(self):
        run = _simulate_game(seed=7)
        attempts = run["event_counts"].get("SHOT_ATTEMPT", 0)
        # 48 minutes of basketball with two teams at ~90 possessions each
        # should produce WAY more than the previous broken 20.
        assert attempts >= 100, f"Only {attempts} shot attempts in 4 quarters"

    def test_shot_clock_violations_no_longer_dominate(self):
        run = _simulate_game(seed=7)
        violations = run["event_counts"].get("SHOT_CLOCK_VIOLATION", 0)
        possessions = run["engine"].stats.possessions_simulated
        assert possessions > 0
        # More than half of possessions ending in shot-clock violations is a
        # bug, not realistic. Cap the ratio to a sane upper bound.
        assert violations / possessions < 0.25, (
            f"{violations} shot-clock violations across {possessions} possessions"
        )

    def test_shot_clock_violation_emits_turnover(self):
        run = _simulate_game(seed=7)
        counts = run["event_counts"]
        violations = counts.get("SHOT_CLOCK_VIOLATION", 0)
        turnovers = counts.get("TURNOVER", 0)
        # Every shot-clock violation pairs with a turnover event.
        # Other turnovers (passes stolen, etc.) also contribute.
        assert turnovers >= violations

    def test_both_teams_score_in_double_digits(self):
        run = _simulate_game(seed=7)
        game = run["game"]
        assert game.score["home"] >= 20
        assert game.score["away"] >= 20

    def test_ball_handler_cell_changes(self):
        # Run a single quarter; assert at least one DRIBBLE_MOVE or DRIVE
        # was emitted from cells other than the default D6.
        run = _simulate_game(seed=7, quarters=1, quarter_length=120.0)
        cells_seen: set[str] = set()
        for event in run["bus"].history:
            if event.event_type == EventType.SHOT_ATTEMPT:
                cell = event.data.get("cell", "")
                if cell:
                    cells_seen.add(cell)
        assert len(cells_seen) >= 2, (
            f"Shots only from {cells_seen}; ball handler never moved"
        )


class TestDeterminism:
    """Same seed + same wiring = identical events and score."""

    def test_game_is_reproducible(self):
        r1 = _simulate_game(seed=2024, quarters=2, quarter_length=300.0)
        r2 = _simulate_game(seed=2024, quarters=2, quarter_length=300.0)
        assert r1["game"].score == r2["game"].score
        assert r1["event_counts"] == r2["event_counts"]


class TestAssistWindow:
    """Assist should only be credited within ASSIST_WINDOW_ACTIONS after a pass."""

    def test_assist_after_immediate_shot(self):
        from basketball_sim.core.types import GameEvent as GE

        tracker = StatsTracker()
        tracker.register_team("t1")
        tracker.register_player("passer", "t1")
        tracker.register_player("shooter", "t1")

        tracker.handle_event(GE(event_type=EventType.PASS_COMPLETED, player_id="passer"))
        tracker.handle_event(GE(
            event_type=EventType.SHOT_MADE, player_id="shooter",
            data={"points": 2},
        ))
        p = tracker.get_team_stats("t1").players["passer"]
        assert p.assists == 1

    def test_no_assist_after_many_actions(self):
        from basketball_sim.core.types import GameEvent as GE

        tracker = StatsTracker()
        tracker.register_team("t1")
        tracker.register_player("passer", "t1")
        tracker.register_player("shooter", "t1")

        tracker.handle_event(GE(event_type=EventType.PASS_COMPLETED, player_id="passer"))
        # Simulate several shot attempts (dribbles would also count as actions
        # but shot_attempt is what the tracker observes directly).
        for _ in range(5):
            tracker.handle_event(GE(
                event_type=EventType.SHOT_ATTEMPT, player_id="shooter",
                data={"shot_type": "three_pointer"},
            ))
            tracker.handle_event(GE(
                event_type=EventType.SHOT_MISSED, player_id="shooter",
            ))
        tracker.handle_event(GE(
            event_type=EventType.SHOT_MADE, player_id="shooter",
            data={"points": 2},
        ))
        p = tracker.get_team_stats("t1").players["passer"]
        # Too many actions elapsed; the pass should not count as an assist.
        assert p.assists == 0


class TestTopOfTheKeyIsAThree:
    """Grid regression test: D7 is above the arc and must register as a three."""

    def test_d7_is_three(self):
        from basketball_sim.core.grid import COURT
        assert COURT.get("D7").is_three is True
        assert COURT.get("D6").is_three is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
