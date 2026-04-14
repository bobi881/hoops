"""Offensive AI -- decides what the ball handler does next.

Reads matchup state, grid positions, help defense, shot clock, and
player tendencies to make realistic basketball decisions. This replaces
the StubOffensiveAI from Phase 1.
"""

from __future__ import annotations

import random
from typing import Any

from basketball_sim.core.engine import OffensiveAI
from basketball_sim.core.grid import COURT
from basketball_sim.core.types import (
    Action,
    ActionType,
    BallHandlerRhythm,
    DefenderBalance,
    DefenderPositioning,
    GameState,
    HelpDefenseStatus,
    MatchupState,
    PossessionState,
)


class BasicOffensiveAI(OffensiveAI):
    """Basketball-aware offensive AI.

    Decision tree:
    1. If defender is beaten/blown by -> drive or shoot
    2. If open shot available -> shoot
    3. If good passing lane open -> pass
    4. If shot clock is low -> force action
    5. Otherwise -> dribble move to create advantage
    """

    def __init__(self, move_registry: dict[str, Any] | None = None) -> None:
        self._moves = move_registry or {}

    def decide(self, possession: PossessionState, game: GameState) -> Action:
        """Pick the next offensive action based on game state."""
        rng = game.rng
        bh = possession.ball_handler
        matchup = bh.matchup
        player = bh.player
        cell = bh.cell
        shot_clock = possession.shot_clock
        n_actions = len(possession.actions_this_possession)

        # --- Shot clock pressure ---
        if shot_clock <= 4.0:
            return self._desperate_shot(player, cell, rng)

        if shot_clock <= 8.0:
            # Need to look to score soon
            return self._late_clock_decision(possession, game, matchup, rng)

        # --- Defender beaten: attack the basket ---
        if matchup.positioning in (
            DefenderPositioning.BEATEN,
            DefenderPositioning.BLOWN_BY,
        ):
            return self._attack_basket(player, cell, matchup, rng)

        # --- Defender off balance: capitalize ---
        if matchup.balance in (
            DefenderBalance.STUMBLING,
            DefenderBalance.ON_FLOOR,
        ):
            return self._capitalize_off_balance(player, cell, matchup, rng)

        # --- Good shooting opportunity ---
        shot_action = self._evaluate_shot_opportunity(
            player, cell, matchup, rng
        )
        if shot_action is not None:
            return shot_action

        # --- Pass to open teammate ---
        if n_actions >= 2 and rng.random() < self._pass_probability(player, possession):
            pass_action = self._find_best_pass(possession, game, rng)
            if pass_action is not None:
                return pass_action

        # --- Dribble move to create advantage ---
        return self._pick_dribble_move(player, matchup, cell, n_actions, rng)

    def force_shot(self, possession: PossessionState, game: GameState) -> Action:
        """Force a shot when the possession is stuck."""
        player = possession.ball_handler.player
        cell = possession.ball_handler.cell
        return self._desperate_shot(player, cell, game.rng)

    # ------------------------------------------------------------------
    # Internal decision helpers
    # ------------------------------------------------------------------

    def _desperate_shot(self, player: Any, cell: str, rng: random.Random) -> Action:
        """Last-second heave."""
        cell_meta = COURT.get(cell) if COURT.is_valid(cell) else None
        is_three = cell_meta.is_three if cell_meta else False
        shot_type = "contested_three" if is_three else "contested_mid_range"

        return Action(
            action_type=ActionType.SHOT,
            player_id=player.player_id,
            data={"shot_type": shot_type, "forced": True, "shot_clock_pressure": True},
            time_cost=0.5 + rng.random() * 0.5,
        )

    def _late_clock_decision(
        self,
        possession: PossessionState,
        game: GameState,
        matchup: MatchupState,
        rng: random.Random,
    ) -> Action:
        """Decision when shot clock is between 4-8 seconds."""
        player = possession.ball_handler.player
        cell = possession.ball_handler.cell

        # If any advantage exists, shoot
        if matchup.positioning != DefenderPositioning.LOCKED_UP:
            return self._take_shot(player, cell, matchup, rng)

        # If off-balance defender, one more move then shoot
        if matchup.balance != DefenderBalance.SET:
            return self._take_shot(player, cell, matchup, rng)

        # Try a quick move to create separation
        if rng.random() < 0.4:
            return self._pick_dribble_move(
                player, matchup, cell, 10, rng  # high action count biases toward simple moves
            )

        return self._take_shot(player, cell, matchup, rng)

    def _attack_basket(
        self, player: Any, cell: str, matchup: MatchupState, rng: random.Random
    ) -> Action:
        """Drive to the basket when defender is beaten."""
        cell_meta = COURT.get(cell) if COURT.is_valid(cell) else None

        # If already close to basket, finish
        if cell_meta and cell_meta.is_paint:
            if player.attributes.dunk >= 70 and rng.random() < 0.4:
                shot_type = "dunk"
            else:
                shot_type = "driving_layup"
            return Action(
                action_type=ActionType.SHOT,
                player_id=player.player_id,
                data={"shot_type": shot_type, "in_rhythm": True},
                time_cost=0.8 + rng.random() * 0.4,
            )

        # Drive toward basket
        return Action(
            action_type=ActionType.DRIVE,
            player_id=player.player_id,
            data={"from_cell": cell, "direction": "basket"},
            time_cost=1.0 + rng.random() * 0.5,
        )

    def _capitalize_off_balance(
        self, player: Any, cell: str, matchup: MatchupState, rng: random.Random
    ) -> Action:
        """Take advantage of a stumbling/floored defender."""
        cell_meta = COURT.get(cell) if COURT.is_valid(cell) else None

        # Pull-up jumper if at shooting distance
        if cell_meta and (cell_meta.is_three or cell_meta.is_midrange):
            shot_type = "pull_up_three" if cell_meta.is_three else "pull_up_mid"
            return Action(
                action_type=ActionType.SHOT,
                player_id=player.player_id,
                data={"shot_type": shot_type, "defender_down": True},
                time_cost=0.8 + rng.random() * 0.4,
            )

        # Otherwise drive
        return Action(
            action_type=ActionType.DRIVE,
            player_id=player.player_id,
            data={"from_cell": cell, "direction": "basket"},
            time_cost=1.0 + rng.random() * 0.5,
        )

    def _evaluate_shot_opportunity(
        self, player: Any, cell: str, matchup: MatchupState, rng: random.Random
    ) -> Action | None:
        """Check if current position offers a good shot. Returns None if not."""
        cell_meta = COURT.get(cell) if COURT.is_valid(cell) else None
        if cell_meta is None:
            return None

        # Calculate openness from matchup
        openness = _matchup_openness(matchup)

        # Decision thresholds based on shot type and player ability
        if cell_meta.is_three:
            threshold = 0.55 - (player.attributes.three_point / 100.0) * 0.25
            if openness > threshold:
                shot_type = "corner_three" if cell_meta.is_corner_three else "three_pointer"
                return Action(
                    action_type=ActionType.SHOT,
                    player_id=player.player_id,
                    data={"shot_type": shot_type},
                    time_cost=0.8 + rng.random() * 0.4,
                )
        elif cell_meta.is_midrange:
            threshold = 0.45 - (player.attributes.mid_range / 100.0) * 0.20
            if openness > threshold:
                return Action(
                    action_type=ActionType.SHOT,
                    player_id=player.player_id,
                    data={"shot_type": "mid_range"},
                    time_cost=0.8 + rng.random() * 0.4,
                )
        elif cell_meta.is_paint or cell_meta.is_restricted_area:
            threshold = 0.30
            if openness > threshold:
                shot_type = "layup" if rng.random() > 0.3 else "floater"
                return Action(
                    action_type=ActionType.SHOT,
                    player_id=player.player_id,
                    data={"shot_type": shot_type},
                    time_cost=0.6 + rng.random() * 0.3,
                )

        return None

    def _pass_probability(self, player: Any, possession: PossessionState) -> float:
        """Calculate how likely the ball handler is to pass."""
        # Pass-first players pass more
        base = 1.0 - player.tendencies.pass_first_vs_score  # 0=scorer, 1=passer
        # More actions = more likely to pass (ball movement)
        action_factor = min(0.2, len(possession.actions_this_possession) * 0.04)
        # Good passers pass more
        vision_factor = player.attributes.passing_vision / 100.0 * 0.15
        return min(0.7, base * 0.4 + action_factor + vision_factor)

    def _find_best_pass(
        self, possession: PossessionState, game: GameState, rng: random.Random
    ) -> Action | None:
        """Find the best passing target."""
        passer = possession.ball_handler
        candidates: list[tuple[float, Any]] = []

        for off_ball in possession.off_ball_offense:
            # Score based on openness and catch readiness
            score = off_ball.openness * 0.6 + off_ball.catch_readiness * 0.4

            # Bonus for cutters
            if off_ball.is_cutting:
                score += 0.2

            # Distance penalty
            distance = COURT.manhattan_distance(passer.cell, off_ball.cell)
            score -= distance * 0.03

            candidates.append((score, off_ball))

        if not candidates:
            return None

        # Sort by score and pick from top candidates with some randomness
        candidates.sort(key=lambda x: x[0], reverse=True)
        best_score = candidates[0][0]

        # Only pass if the best option is decent
        if best_score < 0.25:
            return None

        # Pick from top 2 candidates randomly
        top = candidates[:min(2, len(candidates))]
        _, target = rng.choice(top)

        return Action(
            action_type=ActionType.PASS,
            player_id=passer.player.player_id,
            data={
                "target_id": target.player.player_id,
                "target_cell": target.cell,
                "pass_type": "chest_pass",
            },
            time_cost=0.8 + rng.random() * 0.4,
        )

    def _pick_dribble_move(
        self,
        player: Any,
        matchup: MatchupState,
        cell: str,
        n_actions: int,
        rng: random.Random,
    ) -> Action:
        """Select a dribble move based on situation and player repertoire."""
        available_moves = player.move_repertoire if player.move_repertoire else [
            "crossover", "hesitation", "jab_step"
        ]

        # Filter to moves the player can actually do (check registry)
        valid_moves = []
        for move_id in available_moves:
            if move_id in self._moves:
                move_data = self._moves[move_id]
                req = move_data.required_attributes
                can_do = all(
                    getattr(player.attributes, attr, 0) >= val
                    for attr, val in req.items()
                )
                if can_do:
                    valid_moves.append(move_id)
            else:
                valid_moves.append(move_id)

        if not valid_moves:
            valid_moves = ["crossover", "hesitation", "jab_step"]

        # Weight selection based on situation
        weights: dict[str, float] = {}
        for move_id in valid_moves:
            w = 1.0

            # Early in possession: prefer setup moves
            if n_actions < 2 and move_id in ("jab_step", "hesitation"):
                w *= 1.5

            # Defender shifting: crossovers are more effective
            if matchup.balance == DefenderBalance.SHIFTING:
                if move_id in ("crossover", "behind_the_back", "spin_move"):
                    w *= 1.8

            # Defender reaching: spin moves exploit this
            if matchup.stance.name == "REACHING":
                if move_id in ("spin_move", "behind_the_back"):
                    w *= 2.0

            # Step back for shooting separation
            if matchup.positioning == DefenderPositioning.LOCKED_UP:
                if move_id == "step_back":
                    w *= 1.3

            weights[move_id] = w

        # Weighted random choice
        moves_list = list(weights.keys())
        weights_list = list(weights.values())
        chosen = rng.choices(moves_list, weights=weights_list, k=1)[0]

        return Action(
            action_type=ActionType.DRIBBLE_MOVE,
            player_id=player.player_id,
            data={"move": chosen},
            time_cost=1.2 + rng.random() * 0.8,
        )

    def _take_shot(
        self, player: Any, cell: str, matchup: MatchupState, rng: random.Random
    ) -> Action:
        """Take whatever shot is available from current position."""
        cell_meta = COURT.get(cell) if COURT.is_valid(cell) else None

        if cell_meta is None:
            shot_type = "mid_range"
        elif cell_meta.is_three:
            shot_type = "corner_three" if cell_meta.is_corner_three else "three_pointer"
        elif cell_meta.is_paint or cell_meta.is_restricted_area:
            shot_type = "driving_layup"
        else:
            shot_type = "mid_range"

        return Action(
            action_type=ActionType.SHOT,
            player_id=player.player_id,
            data={"shot_type": shot_type},
            time_cost=0.8 + rng.random() * 0.4,
        )


def _matchup_openness(matchup: MatchupState) -> float:
    """Calculate how open the shooter is from matchup state (0-1)."""
    # Positioning contribution
    pos_open = {
        DefenderPositioning.LOCKED_UP: 0.10,
        DefenderPositioning.TRAILING: 0.40,
        DefenderPositioning.HALF_STEP_BEHIND: 0.60,
        DefenderPositioning.BEATEN: 0.85,
        DefenderPositioning.BLOWN_BY: 1.0,
    }[matchup.positioning]

    # Balance contribution
    bal_factor = {
        DefenderBalance.SET: 1.0,
        DefenderBalance.SHIFTING: 0.85,
        DefenderBalance.OFF_BALANCE: 0.60,
        DefenderBalance.STUMBLING: 0.30,
        DefenderBalance.ON_FLOOR: 0.0,
    }[matchup.balance]

    # Contest = positioning openness reduced by defender's ability to contest
    return pos_open * (2.0 - bal_factor) / 2.0
