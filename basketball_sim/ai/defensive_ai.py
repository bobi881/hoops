"""Defensive AI -- coverage decisions, help rotations, closeout logic.

Reacts to offensive actions by deciding how the defense adjusts.
Manages help defense rotations, closeouts on shooters, and
defensive scheme adherence.
"""

from __future__ import annotations

import random

from basketball_sim.core.engine import DefensiveAI
from basketball_sim.core.grid import COURT
from basketball_sim.core.types import (
    Action,
    ActionType,
    DefenderPositioning,
    EventType,
    GameEvent,
    GameState,
    HelpDefenseStatus,
    PossessionState,
)


class BasicDefensiveAI(DefensiveAI):
    """Basketball-aware defensive AI.

    Handles:
    - Help defense rotation triggers
    - Closeout decisions on shooters
    - Steal attempt decisions
    - Shot contest adjustments
    """

    def react(
        self, action: Action, possession: PossessionState, game: GameState
    ) -> list[GameEvent]:
        """Generate defensive reaction events based on the offensive action."""
        events: list[GameEvent] = []
        rng = game.rng
        matchup = possession.ball_handler.matchup

        if action.action_type == ActionType.DRIBBLE_MOVE:
            events.extend(self._react_to_dribble(possession, matchup, rng))
        elif action.action_type == ActionType.DRIVE:
            events.extend(self._react_to_drive(possession, matchup, rng))
        elif action.action_type == ActionType.PASS:
            events.extend(self._react_to_pass(possession, action, rng))
        elif action.action_type == ActionType.SHOT:
            events.extend(self._react_to_shot(possession, matchup, rng))

        return events

    def _react_to_dribble(
        self,
        possession: PossessionState,
        matchup: HelpDefenseStatus | object,
        rng: random.Random,
    ) -> list[GameEvent]:
        """React to a dribble move -- possibly trigger help defense."""
        events: list[GameEvent] = []
        matchup_state = possession.ball_handler.matchup

        # If defender is getting beaten, check for help defense
        if matchup_state.positioning in (
            DefenderPositioning.BEATEN,
            DefenderPositioning.BLOWN_BY,
        ):
            # Check if a help defender is nearby
            help_available = self._check_help_availability(possession)

            if help_available and matchup_state.help_status == HelpDefenseStatus.NO_HELP:
                # Trigger help rotation
                matchup_state.help_status = HelpDefenseStatus.HELP_ROTATING
                events.append(GameEvent(
                    event_type=EventType.DRIBBLE_MOVE,
                    data={"defensive_adjustment": "help_rotating"},
                    tags=["help_defense_rotating"],
                ))
            elif matchup_state.help_status == HelpDefenseStatus.HELP_ROTATING:
                # Help arrives
                if rng.random() < 0.6:
                    matchup_state.help_status = HelpDefenseStatus.HELP_COMMITTED
                    events.append(GameEvent(
                        event_type=EventType.DRIBBLE_MOVE,
                        data={"defensive_adjustment": "help_committed"},
                        tags=["help_defense_committed"],
                    ))

        # Steal attempt on loose handles
        if matchup_state.positioning == DefenderPositioning.LOCKED_UP:
            steal_chance = self._calculate_steal_chance(possession, rng)
            if rng.random() < steal_chance:
                events.append(GameEvent(
                    event_type=EventType.STEAL,
                    player_id=(
                        possession.defense[0].player.player_id
                        if possession.defense
                        else ""
                    ),
                    data={"steal_type": "on_ball"},
                    tags=["steal_attempt", "on_ball_steal"],
                ))

        return events

    def _react_to_drive(
        self,
        possession: PossessionState,
        matchup: object,
        rng: random.Random,
    ) -> list[GameEvent]:
        """React to a drive -- help defense and shot blocking."""
        events: list[GameEvent] = []
        matchup_state = possession.ball_handler.matchup

        # Drives always trigger help defense check
        help_available = self._check_help_availability(possession)

        if help_available:
            if matchup_state.help_status in (
                HelpDefenseStatus.NO_HELP,
                HelpDefenseStatus.HELP_AVAILABLE,
            ):
                matchup_state.help_status = HelpDefenseStatus.HELP_ROTATING
                events.append(GameEvent(
                    event_type=EventType.DRIBBLE_MOVE,
                    data={"defensive_adjustment": "help_on_drive"},
                    tags=["help_defense_rotating", "protecting_rim"],
                ))

        # Shot block attempt if ball handler is near the basket
        bh_cell = possession.ball_handler.cell
        if COURT.is_valid(bh_cell) and COURT.get(bh_cell).is_paint:
            for defender in possession.defense:
                if COURT.is_valid(defender.cell) and COURT.get(defender.cell).is_paint:
                    block_chance = defender.player.attributes.block / 100.0 * 0.15
                    if rng.random() < block_chance:
                        events.append(GameEvent(
                            event_type=EventType.BLOCK,
                            player_id=defender.player.player_id,
                            data={"block_type": "at_rim"},
                            tags=["block", "rim_protection"],
                        ))
                        break

        return events

    def _react_to_pass(
        self,
        possession: PossessionState,
        action: Action,
        rng: random.Random,
    ) -> list[GameEvent]:
        """React to a pass -- recover help defense, close out on receiver."""
        events: list[GameEvent] = []
        matchup_state = possession.ball_handler.matchup

        # Help defense recovers on a pass (ball movement resets help)
        if matchup_state.help_status in (
            HelpDefenseStatus.HELP_ROTATING,
            HelpDefenseStatus.HELP_COMMITTED,
        ):
            matchup_state.help_status = HelpDefenseStatus.HELP_RECOVERED
            events.append(GameEvent(
                event_type=EventType.PASS_COMPLETED,
                data={"defensive_adjustment": "help_recovering"},
                tags=["defense_recovering"],
            ))

        return events

    def _react_to_shot(
        self,
        possession: PossessionState,
        matchup: object,
        rng: random.Random,
    ) -> list[GameEvent]:
        """React to a shot attempt -- contest or block."""
        events: list[GameEvent] = []
        matchup_state = possession.ball_handler.matchup

        # If help defense was committed, they might contest the shot
        if matchup_state.help_status == HelpDefenseStatus.HELP_COMMITTED:
            events.append(GameEvent(
                event_type=EventType.SHOT_ATTEMPT,
                data={"defensive_adjustment": "help_contest"},
                tags=["help_contest"],
            ))

        return events

    def _check_help_availability(self, possession: PossessionState) -> bool:
        """Check if any help defender is close enough to help."""
        bh_cell = possession.ball_handler.cell

        for defender in possession.defense:
            if not COURT.is_valid(defender.cell) or not COURT.is_valid(bh_cell):
                continue
            dist = COURT.manhattan_distance(defender.cell, bh_cell)
            # Help is available if a defender is within 2-3 cells
            if 1 <= dist <= 3:
                return True
        return False

    def _calculate_steal_chance(
        self, possession: PossessionState, rng: random.Random
    ) -> float:
        """Calculate the probability of a steal attempt succeeding."""
        if not possession.defense:
            return 0.0

        defender = possession.defense[0].player
        attacker = possession.ball_handler.player

        # Base steal chance from defender's steal rating
        base = defender.attributes.steal / 100.0 * 0.04  # max ~4% per action

        # Adjusted by ball handler's ball handling
        handle_factor = attacker.attributes.ball_handling / 100.0
        base *= (1.2 - handle_factor)  # worse handlers = more steals

        return max(0.005, min(0.08, base))
