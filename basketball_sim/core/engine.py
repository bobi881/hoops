"""Game engine -- the main simulation loop.

Action-based, not tick-based. The game advances when someone does something.
Quarter loop calls possession loop. Each possession is a sequence of actions
until shot/turnover/foul/shot-clock-violation.
"""

from __future__ import annotations

import logging
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

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
    PossessionResult,
    PossessionState,
    RulesConfig,
)

logger = logging.getLogger(__name__)

# Safety valve: max actions per possession to prevent infinite loops
MAX_ACTIONS_PER_POSSESSION = 30


# ---------------------------------------------------------------------------
# Abstract interfaces for pluggable components
# ---------------------------------------------------------------------------

class OffensiveAI(ABC):
    """Decides what the ball handler does next."""

    @abstractmethod
    def decide(self, possession: PossessionState, game: GameState) -> Action:
        """Pick the next action for the ball handler."""

    @abstractmethod
    def force_shot(self, possession: PossessionState, game: GameState) -> Action:
        """Force a shot attempt (safety valve when possession is stuck)."""


class DefensiveAI(ABC):
    """Reacts to offensive actions."""

    @abstractmethod
    def react(
        self, action: Action, possession: PossessionState, game: GameState
    ) -> list[GameEvent]:
        """Generate defensive reaction events."""


class ActionResolver(ABC):
    """Resolves an action through the state machine + modifier pipeline."""

    @abstractmethod
    def resolve(
        self,
        action: Action,
        matchup: MatchupState,
        context: ActionContext,
    ) -> ActionResult:
        """Resolve an action and return the result."""


# ---------------------------------------------------------------------------
# Stub implementations (replaced in Phase 2-3)
# ---------------------------------------------------------------------------

class StubOffensiveAI(OffensiveAI):
    """Placeholder AI that alternates between dribble moves and shots."""

    def decide(self, possession: PossessionState, game: GameState) -> Action:
        n = len(possession.actions_this_possession)
        rng = game.rng

        # Simple pattern: dribble a few times, then shoot
        if n < 3:
            return Action(
                action_type=ActionType.DRIBBLE_MOVE,
                player_id=possession.ball_handler.player.player_id,
                data={"move": "crossover"},
                time_cost=1.5 + rng.random(),
            )
        return Action(
            action_type=ActionType.SHOT,
            player_id=possession.ball_handler.player.player_id,
            data={"shot_type": "mid_range"},
            time_cost=1.0 + rng.random() * 0.5,
        )

    def force_shot(self, possession: PossessionState, game: GameState) -> Action:
        return Action(
            action_type=ActionType.SHOT,
            player_id=possession.ball_handler.player.player_id,
            data={"shot_type": "contested_three", "forced": True},
            time_cost=0.5,
        )


class StubDefensiveAI(DefensiveAI):
    """Placeholder that generates no defensive events."""

    def react(
        self, action: Action, possession: PossessionState, game: GameState
    ) -> list[GameEvent]:
        return []


class StubResolver(ActionResolver):
    """Placeholder resolver that produces basic results.

    Dribble moves always succeed. Shots make/miss at 45%.
    This will be replaced with the real multi-axis state resolver in Phase 2.
    """

    def __init__(self, pipeline: ModifierPipeline) -> None:
        self._pipeline = pipeline

    def resolve(
        self,
        action: Action,
        matchup: MatchupState,
        context: ActionContext,
    ) -> ActionResult:
        rng = context.rng

        if action.action_type == ActionType.DRIBBLE_MOVE:
            return ActionResult(
                new_matchup=matchup,
                events=[
                    GameEvent(
                        event_type=EventType.DRIBBLE_MOVE,
                        player_id=action.player_id,
                        data=action.data,
                        tags=["dribble_move"],
                    )
                ],
                tags=["dribble_move"],
            )

        if action.action_type == ActionType.SHOT:
            made = rng.random() < 0.45
            points = 3 if "three" in action.data.get("shot_type", "") else 2
            event_type = EventType.SHOT_MADE if made else EventType.SHOT_MISSED
            tags = ["shot_made" if made else "shot_missed"]

            return ActionResult(
                events=[
                    GameEvent(
                        event_type=EventType.SHOT_ATTEMPT,
                        player_id=action.player_id,
                        data=action.data,
                        tags=["shot_attempt"],
                    ),
                    GameEvent(
                        event_type=event_type,
                        player_id=action.player_id,
                        data={**action.data, "points": points if made else 0},
                        tags=tags,
                    ),
                ],
                tags=tags,
                ends_possession=True,
                score_change=points if made else 0,
            )

        # Default: action with no special effect
        return ActionResult(
            events=[
                GameEvent(
                    event_type=EventType.TURNOVER,
                    player_id=action.player_id,
                    data=action.data,
                    tags=["unhandled_action"],
                )
            ],
            ends_possession=True,
        )


# ---------------------------------------------------------------------------
# Timing / profiling
# ---------------------------------------------------------------------------

@dataclass
class EngineStats:
    """Performance counters for profiling."""
    possessions_simulated: int = 0
    actions_resolved: int = 0
    total_time_seconds: float = 0.0
    possession_times: list[float] = field(default_factory=list)

    @property
    def avg_time_per_possession(self) -> float:
        if not self.possession_times:
            return 0.0
        return sum(self.possession_times) / len(self.possession_times)


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------

class GameEngine:
    """Main simulation engine.

    Orchestrates the game loop: quarters -> possessions -> actions.
    All basketball logic is delegated to pluggable components
    (AI, resolver, modifiers) that can be swapped without touching
    this class.
    """

    def __init__(
        self,
        event_bus: EventBus,
        pipeline: ModifierPipeline,
        offensive_ai: OffensiveAI | None = None,
        defensive_ai: DefensiveAI | None = None,
        resolver: ActionResolver | None = None,
        rules: RulesConfig | None = None,
    ) -> None:
        self.bus = event_bus
        self.pipeline = pipeline
        self.offensive_ai = offensive_ai or StubOffensiveAI()
        self.defensive_ai = defensive_ai or StubDefensiveAI()
        self.resolver = resolver or StubResolver(pipeline)
        self.rules = rules or RulesConfig()
        self.stats = EngineStats()

    def simulate_game(self, game: GameState) -> GameState:
        """Simulate a complete game and return the final state."""
        start = time.monotonic()

        self.bus.emit(GameEvent(event_type=EventType.GAME_START))

        for quarter in range(1, self.rules.num_quarters + 1):
            game.quarter = quarter
            game.game_clock = self.rules.quarter_length
            self._simulate_quarter(game)

        # TODO: overtime logic

        self.bus.emit(
            GameEvent(
                event_type=EventType.GAME_END,
                data={"score": dict(game.score)},
            )
        )

        self.stats.total_time_seconds = time.monotonic() - start
        logger.info(
            "Game complete: %s | %d possessions, %d actions in %.3fs",
            game.score,
            self.stats.possessions_simulated,
            self.stats.actions_resolved,
            self.stats.total_time_seconds,
        )
        return game

    def _simulate_quarter(self, game: GameState) -> None:
        """Simulate one quarter."""
        self.bus.emit(
            GameEvent(
                event_type=EventType.QUARTER_START,
                data={"quarter": game.quarter},
                quarter=game.quarter,
            )
        )

        while game.game_clock > 0:
            possession = self._build_possession(game)
            result = self._simulate_possession(possession, game)

            # Update game state from possession result
            game.game_clock -= result.time_elapsed
            if game.game_clock < 0:
                game.game_clock = 0

            # Apply score
            if result.score_change > 0:
                if game.possession_team_id == game.home_team.team_id:
                    game.score["home"] += result.score_change
                else:
                    game.score["away"] += result.score_change

            # Swap possession (unless offensive rebound)
            if not result.offensive_rebound:
                if game.possession_team_id == game.home_team.team_id:
                    game.possession_team_id = game.away_team.team_id
                else:
                    game.possession_team_id = game.home_team.team_id

        self.bus.emit(
            GameEvent(
                event_type=EventType.QUARTER_END,
                data={"quarter": game.quarter, "score": dict(game.score)},
                quarter=game.quarter,
            )
        )

    def _simulate_possession(
        self, possession: PossessionState, game: GameState
    ) -> PossessionResult:
        """Simulate a single possession: action -> resolve -> emit -> repeat."""
        poss_start = time.monotonic()
        events: list[GameEvent] = []
        action_count = 0
        shot_clock = self.rules.shot_clock

        self.bus.emit(
            GameEvent(
                event_type=EventType.POSSESSION_START,
                data={"team": possession.offensive_team_id},
                game_clock=game.game_clock,
                quarter=game.quarter,
            )
        )

        while not possession.is_resolved:
            # 1. Offensive AI decides next action
            action = self.offensive_ai.decide(possession, game)

            # 2. Defensive AI reacts
            def_events = self.defensive_ai.react(action, possession, game)
            events.extend(def_events)
            self.bus.emit_many(def_events)

            # 3. Build context and resolve the action
            context = ActionContext(
                action=action,
                attacker=possession.ball_handler.player,
                defender=(
                    possession.defense[0].player
                    if possession.defense
                    else possession.ball_handler.player  # fallback for stub
                ),
                matchup=possession.ball_handler.matchup,
                possession=possession,
                game_state=game,
                rng=game.rng,
                cell=possession.ball_handler.cell,
            )

            result = self.resolver.resolve(action, possession.ball_handler.matchup, context)
            self.stats.actions_resolved += 1

            # 4. Apply result to possession state
            if result.new_matchup is not None:
                possession.ball_handler.matchup = result.new_matchup
            possession.actions_this_possession.append(action)
            possession.tags_this_possession.extend(result.tags)

            # 5. Emit events
            for event in result.events:
                event.game_clock = game.game_clock
                event.shot_clock = shot_clock
                event.quarter = game.quarter
            events.extend(result.events)
            self.bus.emit_many(result.events)

            # 6. Check possession-ending conditions
            if result.ends_possession:
                possession.is_resolved = True

            # 7. Advance shot clock
            shot_clock -= action.time_cost
            if shot_clock <= 0 and not possession.is_resolved:
                violation = GameEvent(
                    event_type=EventType.SHOT_CLOCK_VIOLATION,
                    player_id=possession.ball_handler.player.player_id,
                    game_clock=game.game_clock,
                    quarter=game.quarter,
                )
                events.append(violation)
                self.bus.emit(violation)
                possession.is_resolved = True

            # 8. Safety valve
            action_count += 1
            if action_count >= MAX_ACTIONS_PER_POSSESSION and not possession.is_resolved:
                forced = self.offensive_ai.force_shot(possession, game)
                forced_ctx = ActionContext(
                    action=forced,
                    attacker=possession.ball_handler.player,
                    defender=(
                        possession.defense[0].player
                        if possession.defense
                        else possession.ball_handler.player
                    ),
                    matchup=possession.ball_handler.matchup,
                    possession=possession,
                    game_state=game,
                    rng=game.rng,
                    cell=possession.ball_handler.cell,
                )
                forced_result = self.resolver.resolve(
                    forced, possession.ball_handler.matchup, forced_ctx
                )
                self.stats.actions_resolved += 1
                events.extend(forced_result.events)
                self.bus.emit_many(forced_result.events)
                possession.is_resolved = True
                if forced_result.score_change > 0:
                    result = forced_result  # use forced shot's result for scoring

        self.bus.emit(
            GameEvent(
                event_type=EventType.POSSESSION_END,
                data={"team": possession.offensive_team_id},
                game_clock=game.game_clock,
                quarter=game.quarter,
            )
        )

        self.stats.possessions_simulated += 1
        self.stats.possession_times.append(time.monotonic() - poss_start)

        # Calculate time elapsed (sum of action time costs, capped by game clock)
        time_elapsed = self.rules.shot_clock - max(0, shot_clock)
        time_elapsed = min(time_elapsed, game.game_clock)

        # Calculate total score change from events
        total_score = sum(
            e.data.get("points", 0)
            for e in events
            if e.event_type == EventType.SHOT_MADE
        )

        return PossessionResult(
            events=events,
            time_elapsed=time_elapsed,
            score_change=total_score,
            offensive_rebound=False,  # TODO: rebound logic
        )

    def _build_possession(self, game: GameState) -> PossessionState:
        """Create a fresh PossessionState from the current game state.

        In Phase 1 this is simplified -- it picks the first on-court player
        as ball handler. Phase 3 will add proper play calling and positioning.
        """
        if game.possession_team_id == game.home_team.team_id:
            offense = game.home_team
            defense = game.away_team
        else:
            offense = game.away_team
            defense = game.home_team

        # Pick ball handler (first on-court player, or first player)
        off_players = [
            p for p in offense.players if p.player_id in offense.on_court
        ]
        def_players = [
            p for p in defense.players if p.player_id in defense.on_court
        ]

        if not off_players:
            off_players = offense.players[:5]
        if not def_players:
            def_players = defense.players[:5]

        from basketball_sim.core.types import PlayerOnCourt, OffBallState

        ball_handler = PlayerOnCourt(
            player=off_players[0],
            cell="D6",  # default: top of the key
            matchup=MatchupState(),
            is_ball_handler=True,
        )

        off_ball = []
        # Simple default positions for off-ball players
        default_cells = ["B6", "F6", "A5", "G5"]
        for i, player in enumerate(off_players[1:5]):
            cell = default_cells[i] if i < len(default_cells) else "D7"
            off_ball.append(
                OffBallState(
                    player=player,
                    cell=cell,
                    openness=0.3,
                    catch_readiness=0.5,
                )
            )

        def_on_court = []
        def_cells = ["D6", "B6", "F6", "C3", "E3"]
        for i, player in enumerate(def_players[:5]):
            cell = def_cells[i] if i < len(def_cells) else "D5"
            def_on_court.append(
                PlayerOnCourt(player=player, cell=cell)
            )

        return PossessionState(
            ball_handler=ball_handler,
            off_ball_offense=off_ball,
            defense=def_on_court,
            shot_clock=self.rules.shot_clock,
            game_clock=game.game_clock,
            quarter=game.quarter,
            score=dict(game.score),
            offensive_team_id=offense.team_id,
            defensive_team_id=defense.team_id,
        )
