"""Core type definitions for the basketball simulator.

All enums, dataclasses, and type aliases used across the engine.
This is the shared vocabulary -- every module imports from here.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, ClassVar, Protocol


# ---------------------------------------------------------------------------
# Matchup axis enums (the five state machines)
# ---------------------------------------------------------------------------

class DefenderPositioning(Enum):
    """Spatial relationship between defender and attacker."""
    LOCKED_UP = auto()
    TRAILING = auto()
    HALF_STEP_BEHIND = auto()
    BEATEN = auto()
    BLOWN_BY = auto()


class DefenderBalance(Enum):
    """Physical stability of the defender."""
    SET = auto()
    SHIFTING = auto()
    OFF_BALANCE = auto()
    STUMBLING = auto()
    ON_FLOOR = auto()


class DefenderStance(Enum):
    """What the defender is physically doing."""
    GUARDING = auto()
    CLOSING_OUT = auto()
    IN_AIR = auto()
    REACHING = auto()
    RECOVERING = auto()
    HEDGING = auto()
    FLAILING = auto()


class BallHandlerRhythm(Enum):
    """Current mode of the ball handler."""
    SURVEYING = auto()
    GATHERING = auto()
    ATTACKING = auto()
    ELEVATED = auto()
    COMMITTED = auto()


class HelpDefenseStatus(Enum):
    """Status of nearby help defenders."""
    NO_HELP = auto()
    HELP_AVAILABLE = auto()
    HELP_ROTATING = auto()
    HELP_COMMITTED = auto()
    HELP_RECOVERED = auto()


# ---------------------------------------------------------------------------
# Matchup state (combination of all five axes)
# ---------------------------------------------------------------------------

@dataclass
class MatchupState:
    """The full state of a ball-handler vs. primary-defender matchup."""
    positioning: DefenderPositioning = DefenderPositioning.LOCKED_UP
    balance: DefenderBalance = DefenderBalance.SET
    stance: DefenderStance = DefenderStance.GUARDING
    rhythm: BallHandlerRhythm = BallHandlerRhythm.SURVEYING
    help_status: HelpDefenseStatus = HelpDefenseStatus.NO_HELP


# Ordered lists used by the resolver to determine which transitions
# are "favorable" for the attacker on each axis.
POSITIONING_FAVORABLE: list[DefenderPositioning] = [
    DefenderPositioning.TRAILING,
    DefenderPositioning.HALF_STEP_BEHIND,
    DefenderPositioning.BEATEN,
    DefenderPositioning.BLOWN_BY,
]

BALANCE_FAVORABLE: list[DefenderBalance] = [
    DefenderBalance.SHIFTING,
    DefenderBalance.OFF_BALANCE,
    DefenderBalance.STUMBLING,
    DefenderBalance.ON_FLOOR,
]


# ---------------------------------------------------------------------------
# Action types (what a player can do)
# ---------------------------------------------------------------------------

class ActionType(Enum):
    """Top-level categories of actions a player can take."""
    DRIBBLE_MOVE = auto()
    SHOT = auto()
    PASS = auto()
    DRIVE = auto()
    SCREEN = auto()
    POST_MOVE = auto()
    HOLD_BALL = auto()
    REBOUND = auto()
    FOUL = auto()
    TURNOVER = auto()
    FREE_THROW = auto()


@dataclass
class Action:
    """An action taken by a player during a possession."""
    action_type: ActionType
    player_id: str
    data: dict[str, Any] = field(default_factory=dict)
    time_cost: float = 1.5  # seconds this action consumes from the shot clock


# ---------------------------------------------------------------------------
# Events (emitted to the event bus after resolution)
# ---------------------------------------------------------------------------

class EventType(Enum):
    """Categories of events the engine can emit."""
    DRIBBLE_MOVE = auto()
    SHOT_ATTEMPT = auto()
    SHOT_MADE = auto()
    SHOT_MISSED = auto()
    PASS_COMPLETED = auto()
    PASS_INTERCEPTED = auto()
    STEAL = auto()
    TURNOVER = auto()
    FOUL_COMMITTED = auto()
    FREE_THROW = auto()
    REBOUND = auto()
    BLOCK = auto()
    ASSIST = auto()
    ANKLE_BREAKER = auto()
    FAST_BREAK = auto()
    SHOT_CLOCK_VIOLATION = auto()
    POSSESSION_START = auto()
    POSSESSION_END = auto()
    QUARTER_START = auto()
    QUARTER_END = auto()
    GAME_START = auto()
    GAME_END = auto()
    TIMEOUT = auto()
    SUBSTITUTION = auto()


@dataclass
class GameEvent:
    """A single event emitted by the engine."""
    event_type: EventType
    player_id: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    game_clock: float = 0.0
    shot_clock: float = 0.0
    quarter: int = 1


# ---------------------------------------------------------------------------
# Action result (output of a resolver)
# ---------------------------------------------------------------------------

@dataclass
class ActionResult:
    """The result of resolving an action through the state resolver."""
    new_matchup: MatchupState | None = None
    events: list[GameEvent] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    ends_possession: bool = False
    ball_handler_change: str | None = None  # player_id of new ball handler
    score_change: int = 0  # points scored (0, 2, or 3)


# ---------------------------------------------------------------------------
# Modifier types (output of modifier pipeline)
# ---------------------------------------------------------------------------

@dataclass
class Modifier:
    """Output of a single modifier layer.

    All values are additive adjustments to transition probabilities.
    Positive = attacker advantage, negative = defender advantage.
    """
    positioning_boost: float = 0.0
    balance_boost: float = 0.0
    stance_boost: float = 0.0
    rhythm_boost: float = 0.0
    help_boost: float = 0.0
    shot_pct_boost: float = 0.0
    tags: list[str] = field(default_factory=list)


@dataclass
class AggregatedModifier:
    """Combined output of all modifier layers.

    Additive combination -- ordering does NOT matter.
    Each boost is clamped to [-0.25, +0.25] after aggregation.
    """
    positioning_boost: float = 0.0
    balance_boost: float = 0.0
    stance_boost: float = 0.0
    rhythm_boost: float = 0.0
    help_boost: float = 0.0
    shot_pct_boost: float = 0.0
    tags: list[str] = field(default_factory=list)

    # Clamping range for each per-axis boost. Declared as ClassVar so they
    # don't become dataclass fields / show up in __init__ or asdict().
    CLAMP_MIN: ClassVar[float] = -0.25
    CLAMP_MAX: ClassVar[float] = 0.25
    SHOT_CLAMP: ClassVar[float] = 0.15

    def combine(self, mod: Modifier) -> None:
        """Merge another modifier into this aggregate (additive)."""
        self.positioning_boost += mod.positioning_boost
        self.balance_boost += mod.balance_boost
        self.stance_boost += mod.stance_boost
        self.rhythm_boost += mod.rhythm_boost
        self.help_boost += mod.help_boost
        self.shot_pct_boost += mod.shot_pct_boost
        self.tags.extend(mod.tags)

    def clamp(self) -> None:
        """Clamp all per-axis boosts to the allowed range."""
        self.positioning_boost = max(self.CLAMP_MIN, min(self.CLAMP_MAX, self.positioning_boost))
        self.balance_boost = max(self.CLAMP_MIN, min(self.CLAMP_MAX, self.balance_boost))
        self.stance_boost = max(self.CLAMP_MIN, min(self.CLAMP_MAX, self.stance_boost))
        self.rhythm_boost = max(self.CLAMP_MIN, min(self.CLAMP_MAX, self.rhythm_boost))
        self.help_boost = max(self.CLAMP_MIN, min(self.CLAMP_MAX, self.help_boost))
        # shot_pct_boost is clamped to a tighter range since it is a direct
        # percentage addition to the final shot percentage.
        self.shot_pct_boost = max(
            -self.SHOT_CLAMP, min(self.SHOT_CLAMP, self.shot_pct_boost)
        )


# ---------------------------------------------------------------------------
# Player model
# ---------------------------------------------------------------------------

@dataclass
class PlayerAttributes:
    """Core ratings for a player (0-99 scale)."""
    ball_handling: int = 70
    speed: int = 70
    three_point: int = 70
    mid_range: int = 70
    driving_layup: int = 70
    dunk: int = 50
    passing_vision: int = 70
    passing_accuracy: int = 70
    perimeter_defense: int = 70
    interior_defense: int = 70
    steal: int = 70
    block: int = 50
    offensive_rebound: int = 50
    defensive_rebound: int = 70
    strength: int = 70
    vertical: int = 70
    stamina: int = 70
    basketball_iq: int = 70
    screen_setting: int = 50
    post_offense: int = 50
    post_defense: int = 50
    defensive_consistency: int = 70


@dataclass
class ShootingProfile:
    """Detailed shooting data for a player."""
    hot_zones: dict[str, float] = field(default_factory=dict)  # cell_id -> pct modifier
    catch_and_shoot_bonus: float = 0.0
    off_dribble_penalty: float = 0.0
    contest_resistance: float = 0.0  # how much less they drop off when contested
    release_speed: str = "average"  # "slow", "average", "fast", "very_fast"


@dataclass
class PlayerTendencies:
    """How a player chooses to play -- personality, not skill."""
    drive_direction: dict[str, float] = field(
        default_factory=lambda: {"left": 0.5, "right": 0.5}
    )
    iso_frequency: float = 0.3
    post_up_frequency: float = 0.1
    three_vs_midrange: float = 0.5  # 1.0 = always threes, 0.0 = always midrange
    pass_first_vs_score: float = 0.5  # 1.0 = pure scorer, 0.0 = pure passer
    clutch_usage: float = 0.5
    defensive_effort: float = 0.7
    off_ball_movement_quality: float = 0.5
    flashy_play_tendency: float = 0.2
    heat_check_tendency: float = 0.3


@dataclass
class PlayerMentalState:
    """Dynamic mental state that changes during the game."""
    confidence: float = 0.5  # 0-1
    frustration: float = 0.0  # 0-1
    focus: float = 0.8  # 0-1
    momentum: float = 0.0  # -1 to 1
    intimidation: float = 0.0  # 0-1 (how intimidated BY opponents)
    composure: float = 0.7  # 0-1 (resistance to pressure)


@dataclass
class FatigueState:
    """Multi-dimensional fatigue model."""
    cardiovascular: float = 1.0  # 1.0 = fresh, 0.0 = completely gassed
    muscular: float = 1.0
    mental: float = 1.0
    accumulated: float = 1.0  # season-level load


@dataclass
class Player:
    """A basketball player with all attributes, tendencies, and state."""
    player_id: str
    display_name: str
    team_id: str
    position: str  # "PG", "SG", "SF", "PF", "C"
    attributes: PlayerAttributes = field(default_factory=PlayerAttributes)
    shooting: ShootingProfile = field(default_factory=ShootingProfile)
    tendencies: PlayerTendencies = field(default_factory=PlayerTendencies)
    mental: PlayerMentalState = field(default_factory=PlayerMentalState)
    fatigue: FatigueState = field(default_factory=FatigueState)
    badges: list[str] = field(default_factory=list)
    move_repertoire: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# On-court player state (player + position + matchup during a possession)
# ---------------------------------------------------------------------------

@dataclass
class OffBallState:
    """State of an off-ball player during a possession."""
    player: Player
    cell: str  # grid cell, e.g. "A6"
    defender_id: str = ""
    defender_cell: str = ""
    openness: float = 0.3
    catch_readiness: float = 0.5
    is_cutting: bool = False
    is_screening: bool = False
    movement_target: str | None = None
    turns_stationary: int = 0


@dataclass
class PlayerOnCourt:
    """A player's full on-court state during a possession."""
    player: Player
    cell: str
    matchup: MatchupState = field(default_factory=MatchupState)
    is_ball_handler: bool = False


# ---------------------------------------------------------------------------
# Possession and game state
# ---------------------------------------------------------------------------

@dataclass
class PossessionState:
    """Full state of an active possession."""
    ball_handler: PlayerOnCourt
    off_ball_offense: list[OffBallState] = field(default_factory=list)
    defense: list[PlayerOnCourt] = field(default_factory=list)
    shot_clock: float = 24.0
    game_clock: float = 720.0
    quarter: int = 1
    score: dict[str, int] = field(default_factory=lambda: {"home": 0, "away": 0})
    offensive_team_id: str = ""
    defensive_team_id: str = ""
    actions_this_possession: list[Action] = field(default_factory=list)
    tags_this_possession: list[str] = field(default_factory=list)
    is_resolved: bool = False
    is_fast_break: bool = False


@dataclass
class PossessionResult:
    """Outcome of a completed possession."""
    events: list[GameEvent] = field(default_factory=list)
    time_elapsed: float = 0.0
    score_change: int = 0
    offensive_rebound: bool = False
    free_throws: int = 0  # number of FTs awarded


@dataclass
class TeamState:
    """State of a team during a game."""
    team_id: str
    name: str
    players: list[Player] = field(default_factory=list)
    on_court: list[str] = field(default_factory=list)  # player_ids of 5 on court
    timeouts_remaining: int = 7
    team_fouls: int = 0
    in_bonus: bool = False


@dataclass
class GameState:
    """Full state of a game in progress."""
    home_team: TeamState
    away_team: TeamState
    quarter: int = 1
    game_clock: float = 720.0  # seconds remaining in quarter
    possession_team_id: str = ""  # who has the ball
    score: dict[str, int] = field(default_factory=lambda: {"home": 0, "away": 0})
    events: list[GameEvent] = field(default_factory=list)
    rng: random.Random = field(default_factory=lambda: random.Random(42))


# ---------------------------------------------------------------------------
# Rules configuration
# ---------------------------------------------------------------------------

@dataclass
class RulesConfig:
    """Game rules -- swappable for NBA, NCAA, FIBA, etc."""
    quarter_length: float = 720.0  # 12 minutes in seconds
    num_quarters: int = 4
    shot_clock: float = 24.0
    three_point_distance: float = 23.75  # feet (NBA)
    overtime_length: float = 300.0  # 5 minutes
    team_fouls_for_bonus: int = 5
    personal_foul_limit: int = 6
    timeouts_per_half: int = 7


# ---------------------------------------------------------------------------
# Move data (loaded from JSON)
# ---------------------------------------------------------------------------

@dataclass
class MoveData:
    """A dribble move definition loaded from JSON data."""
    move_id: str
    display_name: str
    category: str = ""
    transitions: dict[str, dict[str, dict[str, float]]] = field(default_factory=dict)
    cross_axis_boosts: dict[str, float] = field(default_factory=dict)
    tags_on_success: list[str] = field(default_factory=list)
    tags_on_critical: list[str] = field(default_factory=list)
    energy_cost: float = 0.03
    required_attributes: dict[str, int] = field(default_factory=dict)
    effective_grid_regions: list[str] = field(default_factory=list)
    combo_bonus_after: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Action context (passed to modifiers and resolvers)
# ---------------------------------------------------------------------------

@dataclass
class ActionContext:
    """Context passed to modifier functions and resolvers."""
    action: Action
    attacker: Player
    defender: Player
    matchup: MatchupState
    possession: PossessionState
    game_state: GameState
    rng: random.Random
    cell: str = ""  # grid cell where the action takes place


# ---------------------------------------------------------------------------
# Protocol for pluggable components
# ---------------------------------------------------------------------------

class ModifierFunc(Protocol):
    """Protocol for modifier functions (used by the pipeline)."""
    def __call__(self, context: ActionContext) -> Modifier: ...


class ResolverFunc(Protocol):
    """Protocol for action resolver functions."""
    def __call__(
        self,
        action: Action,
        matchup: MatchupState,
        context: ActionContext,
    ) -> ActionResult: ...
