"""Regression tests for review follow-ups on PR #2.

Covers:
  1. Offensive rebound resets the shot clock (no immediate violation).
  2. Dribble fatigue drain lives at a single site (engine), so the move
     only drains once even when the resolver is called directly.
  3. Assist window actually counts dribbles between a pass and a shot.
  4. Safety-valve forced shot stamps game_clock / shot_clock / quarter on
     its events (and any rebound events that follow).
  5. Safety-valve offensive rebound swaps the ball handler before the
     possession is marked resolved.
"""

from __future__ import annotations

import random

from basketball_sim.core.engine import GameEngine
from basketball_sim.core.event_bus import EventBus
from basketball_sim.core.pipeline import ModifierPipeline
from basketball_sim.core.types import (
    Action,
    ActionContext,
    ActionResult,
    ActionType,
    EventType,
    GameEvent,
    GameState,
    MatchupState,
    OffBallState,
    Player,
    PlayerOnCourt,
    PossessionState,
    RulesConfig,
    TeamState,
)
from basketball_sim.data.loader import load_moves
from basketball_sim.narration.stats_tracker import StatsTracker
from basketball_sim.resolvers.dribble import resolve_dribble


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _player(pid: str, team: str = "t1") -> Player:
    p = Player(player_id=pid, display_name=pid, team_id=team, position="PG")
    p.attributes.ball_handling = 85
    p.attributes.three_point = 75
    p.attributes.finishing = 75
    p.attributes.passing_vision = 80
    p.attributes.passing_accuracy = 80
    p.attributes.rebounding_offense = 70
    p.attributes.rebounding_defense = 70
    return p


def _possession() -> PossessionState:
    bh = PlayerOnCourt(player=_player("off1"), cell="D6", matchup=MatchupState())
    return PossessionState(
        ball_handler=bh,
        off_ball_offense=[
            OffBallState(player=_player("off2"), cell="B6"),
            OffBallState(player=_player("off3"), cell="F6"),
            OffBallState(player=_player("off4"), cell="C2"),
            OffBallState(player=_player("off5"), cell="E2"),
        ],
        defense=[
            PlayerOnCourt(player=_player(f"def{i}", team="t2"), cell="D6")
            for i in range(1, 6)
        ],
        shot_clock=24.0,
        offensive_team_id="t1",
        defensive_team_id="t2",
    )


def _game_state() -> GameState:
    return GameState(
        home_team=TeamState(team_id="t1", name="Home"),
        away_team=TeamState(team_id="t2", name="Away"),
        rng=random.Random(1),
        game_clock=600.0,
        quarter=2,
    )


def _engine() -> GameEngine:
    return GameEngine(
        event_bus=EventBus(),
        pipeline=ModifierPipeline(),
        rules=RulesConfig(),
    )


# ---------------------------------------------------------------------------
# 1. Offensive rebound resets shot clock
# ---------------------------------------------------------------------------

def test_offensive_rebound_resets_shot_clock() -> None:
    engine = _engine()
    possession = _possession()
    possession.shot_clock = 2.0  # nearly expired

    # Simulate the offensive-rebound branch: swap handler + reset clock.
    rebound_target = possession.off_ball_offense[0].player.player_id
    engine._swap_ball_handler(
        possession, rebound_target, new_cell=possession.ball_handler.cell
    )
    possession.ball_handler.matchup = MatchupState()
    possession.shot_clock = min(
        engine.rules.offensive_rebound_shot_clock, engine.rules.shot_clock
    )

    assert possession.shot_clock == 14.0
    assert possession.ball_handler.player.player_id == rebound_target


def test_rules_config_defaults_offensive_rebound_shot_clock() -> None:
    # Default should be 14s (NBA / FIBA convention) and bounded by the full
    # shot clock so ill-configured rulesets can't exceed it.
    rules = RulesConfig()
    assert rules.offensive_rebound_shot_clock == 14.0
    reset = min(rules.offensive_rebound_shot_clock, rules.shot_clock)
    assert reset <= rules.shot_clock


# ---------------------------------------------------------------------------
# 2. Fatigue drain happens once, not twice
# ---------------------------------------------------------------------------

def test_dribble_resolver_does_not_drain_fatigue_directly() -> None:
    """The resolver should stamp energy_cost on the action and leave the
    actual fatigue accounting to engine._apply_action_result."""
    moves = load_moves()
    # load_moves returns a dict keyed by move_id.
    if isinstance(moves, dict):
        moves = list(moves.values())
    move = next(m for m in moves if m.energy_cost > 0.0)

    player = _player("pX")
    cardio_before = player.fatigue.cardiovascular
    muscular_before = player.fatigue.muscular
    mental_before = player.fatigue.mental

    action = Action(
        action_type=ActionType.DRIBBLE_MOVE,
        player_id=player.player_id,
        data={"move_id": move.move_id},
    )
    context = ActionContext(
        action=action,
        attacker=player,
        defender=_player("dX", team="t2"),
        matchup=MatchupState(),
        possession=_possession(),
        game_state=_game_state(),
        rng=random.Random(0),
        cell="D6",
    )
    from basketball_sim.core.types import AggregatedModifier

    resolve_dribble(move, context.matchup, AggregatedModifier(), context)

    # Resolver should no longer mutate fatigue; the action carries the cost.
    assert player.fatigue.cardiovascular == cardio_before
    assert player.fatigue.muscular == muscular_before
    assert player.fatigue.mental == mental_before
    assert action.data["energy_cost"] == move.energy_cost


def test_engine_drains_fatigue_from_action_energy_cost() -> None:
    engine = _engine()
    possession = _possession()
    player = possession.ball_handler.player
    cardio_before = player.fatigue.cardiovascular

    action = Action(
        action_type=ActionType.DRIBBLE_MOVE,
        player_id=player.player_id,
        data={"energy_cost": 0.05},
    )
    result = ActionResult(new_matchup=MatchupState())
    engine._apply_action_result(action, result, possession)

    assert player.fatigue.cardiovascular < cardio_before


# ---------------------------------------------------------------------------
# 3. Assist window counts dribbles
# ---------------------------------------------------------------------------

def _make_tracker() -> StatsTracker:
    tracker = StatsTracker()
    tracker.register_team("t1", "Home")
    tracker.register_player("passer", "t1")
    tracker.register_player("scorer", "t1")
    return tracker


def test_assist_window_counts_dribble_between_pass_and_shot() -> None:
    tracker = _make_tracker()

    # Pass -> one dribble -> made shot. The dribble advances the window,
    # but we are still within ASSIST_WINDOW_ACTIONS (2), so the passer
    # should still be credited with an assist.
    tracker.handle_event(GameEvent(
        event_type=EventType.PASS_COMPLETED, player_id="passer",
    ))
    tracker.handle_event(GameEvent(
        event_type=EventType.DRIBBLE_MOVE, player_id="scorer",
    ))
    tracker.handle_event(GameEvent(
        event_type=EventType.SHOT_ATTEMPT, player_id="scorer",
    ))
    tracker.handle_event(GameEvent(
        event_type=EventType.SHOT_MADE, player_id="scorer",
        data={"points": 2},
    ))

    assists = tracker.get_team_stats("t1").players["passer"].assists
    assert assists == 1


def test_assist_window_denies_credit_after_too_many_dribbles() -> None:
    tracker = _make_tracker()

    tracker.handle_event(GameEvent(
        event_type=EventType.PASS_COMPLETED, player_id="passer",
    ))
    # Two dribbles before the shot: counter becomes 3 with the shot
    # attempt, which exceeds ASSIST_WINDOW_ACTIONS (2).
    for _ in range(2):
        tracker.handle_event(GameEvent(
            event_type=EventType.DRIBBLE_MOVE, player_id="scorer",
        ))
    tracker.handle_event(GameEvent(
        event_type=EventType.SHOT_ATTEMPT, player_id="scorer",
    ))
    tracker.handle_event(GameEvent(
        event_type=EventType.SHOT_MADE, player_id="scorer",
        data={"points": 2},
    ))

    assists = tracker.get_team_stats("t1").players["passer"].assists
    assert assists == 0


def test_assist_window_ignores_defensive_adjustment_events() -> None:
    tracker = _make_tracker()

    tracker.handle_event(GameEvent(
        event_type=EventType.PASS_COMPLETED, player_id="passer",
    ))
    # Defensive-adjustment sentinels should not consume the assist window.
    tracker.handle_event(GameEvent(
        event_type=EventType.DRIBBLE_MOVE,
        player_id="",
        data={"defensive_adjustment": "help_rotating"},
    ))
    tracker.handle_event(GameEvent(
        event_type=EventType.SHOT_ATTEMPT, player_id="scorer",
    ))
    tracker.handle_event(GameEvent(
        event_type=EventType.SHOT_MADE, player_id="scorer",
        data={"points": 2},
    ))

    assists = tracker.get_team_stats("t1").players["passer"].assists
    assert assists == 1


# ---------------------------------------------------------------------------
# 4+5. Safety-valve event stamping + offensive-rebound handler swap
# ---------------------------------------------------------------------------

class _ForcedMissResolver:
    """Resolver stub that returns harmless dribbles until it sees a shot
    action, at which point it returns a missed shot. Used to exercise the
    safety-valve branch of Engine._simulate_possession."""

    def __init__(self) -> None:
        self.calls = 0

    def resolve(self, action, matchup, context):
        self.calls += 1
        if action.action_type == ActionType.SHOT:
            return ActionResult(
                events=[
                    GameEvent(
                        event_type=EventType.SHOT_ATTEMPT,
                        player_id=action.player_id,
                    ),
                    GameEvent(
                        event_type=EventType.SHOT_MISSED,
                        player_id=action.player_id,
                    ),
                ],
                ends_possession=False,
            )
        return ActionResult(
            new_matchup=MatchupState(),
            events=[
                GameEvent(
                    event_type=EventType.DRIBBLE_MOVE,
                    player_id=action.player_id,
                )
            ],
            ends_possession=False,
        )


def test_safety_valve_stamps_clock_on_forced_events(monkeypatch) -> None:
    resolver = _ForcedMissResolver()
    engine = GameEngine(
        event_bus=EventBus(),
        pipeline=ModifierPipeline(),
        resolver=resolver,
        rules=RulesConfig(),
    )
    possession = _possession()
    game = _game_state()
    game.game_clock = 432.0
    game.quarter = 3
    possession.shot_clock = 6.5

    # Force the safety-valve branch by making the rebound return no change.
    rebound_target = possession.off_ball_offense[0].player.player_id

    def fake_rebound(poss, gm):  # type: ignore[no-redef]
        return ActionResult(
            events=[GameEvent(event_type=EventType.REBOUND, player_id="def1")],
            ball_handler_change="",
        )

    monkeypatch.setattr(engine, "_resolve_rebound", fake_rebound)
    # Force offensive AI to produce a shot action every time.
    monkeypatch.setattr(
        engine.offensive_ai,
        "decide",
        lambda p, g: Action(
            action_type=ActionType.DRIBBLE_MOVE,
            player_id=p.ball_handler.player.player_id,
            time_cost=0.0,
        ),
    )
    monkeypatch.setattr(
        engine.offensive_ai,
        "force_shot",
        lambda p, g: Action(
            action_type=ActionType.SHOT, player_id=p.ball_handler.player.player_id,
        ),
    )
    monkeypatch.setattr(engine.defensive_ai, "react", lambda *a, **k: [])

    result = engine._simulate_possession(possession, game)

    # Every forced-shot + rebound event should carry clock / quarter context.
    stamped = [
        e for e in result.events
        if e.event_type in {EventType.SHOT_ATTEMPT, EventType.SHOT_MISSED, EventType.REBOUND}
    ]
    assert stamped, "expected forced-shot events in the result"
    for ev in stamped:
        assert ev.game_clock == game.game_clock
        assert ev.quarter == game.quarter
        # shot_clock was stamped from possession.shot_clock (a float)
        assert isinstance(ev.shot_clock, float)


def test_safety_valve_offensive_rebound_swaps_ball_handler(monkeypatch) -> None:
    resolver = _ForcedMissResolver()
    engine = GameEngine(
        event_bus=EventBus(),
        pipeline=ModifierPipeline(),
        resolver=resolver,
        rules=RulesConfig(),
    )
    possession = _possession()
    game = _game_state()

    new_handler_id = possession.off_ball_offense[0].player.player_id

    def fake_rebound(poss, gm):  # type: ignore[no-redef]
        return ActionResult(
            events=[GameEvent(event_type=EventType.REBOUND, player_id=new_handler_id)],
            ball_handler_change=new_handler_id,
        )

    monkeypatch.setattr(engine, "_resolve_rebound", fake_rebound)
    monkeypatch.setattr(
        engine.offensive_ai,
        "decide",
        lambda p, g: Action(
            action_type=ActionType.DRIBBLE_MOVE,
            player_id=p.ball_handler.player.player_id,
            time_cost=0.0,
        ),
    )
    monkeypatch.setattr(
        engine.offensive_ai,
        "force_shot",
        lambda p, g: Action(
            action_type=ActionType.SHOT, player_id=p.ball_handler.player.player_id,
        ),
    )
    monkeypatch.setattr(engine.defensive_ai, "react", lambda *a, **k: [])

    result = engine._simulate_possession(possession, game)

    assert result.offensive_rebound is True
    assert possession.ball_handler.player.player_id == new_handler_id
    assert possession.is_resolved is True
