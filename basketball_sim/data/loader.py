"""JSON data loader for moves, badges, and other game data.

Loads JSON files from the data/moves/, data/badges/ directories
and converts them into typed dataclass instances.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from basketball_sim.core.types import MoveData

logger = logging.getLogger(__name__)

# Base data directory (relative to this file)
_DATA_DIR = Path(__file__).parent


def _load_json(path: Path) -> Any:
    """Load and parse a JSON file."""
    with open(path, "r") as f:
        return json.load(f)


def load_moves(directory: Path | None = None) -> dict[str, MoveData]:
    """Load all dribble move definitions from JSON files.

    Args:
        directory: Directory containing move JSON files.
                   Defaults to data/moves/.

    Returns:
        Dict of move_id -> MoveData.
    """
    if directory is None:
        directory = _DATA_DIR / "moves"

    registry: dict[str, MoveData] = {}

    if not directory.exists():
        logger.warning("Moves directory not found: %s", directory)
        return registry

    for path in sorted(directory.glob("*.json")):
        try:
            raw = _load_json(path)
            entries = raw if isinstance(raw, list) else [raw]
            for entry in entries:
                move = _parse_move(entry)
                if move.move_id in registry:
                    logger.warning(
                        "Duplicate move ID '%s' in %s (overwriting)",
                        move.move_id,
                        path.name,
                    )
                registry[move.move_id] = move
        except Exception:
            logger.exception("Failed to load moves from %s", path)

    logger.info("Loaded %d dribble moves from %s", len(registry), directory)
    return registry


def _parse_move(data: dict[str, Any]) -> MoveData:
    """Parse a single move entry from JSON into a MoveData dataclass."""
    return MoveData(
        move_id=data["id"],
        display_name=data.get("display_name", data["id"]),
        category=data.get("category", ""),
        transitions=data.get("transitions", {}),
        cross_axis_boosts=data.get("cross_axis_boosts", {}),
        tags_on_success=data.get("tags_on_success", []),
        tags_on_critical=data.get("tags_on_critical", []),
        energy_cost=data.get("energy_cost", 0.03),
        required_attributes=data.get("required_attributes", {}),
        effective_grid_regions=data.get("effective_grid_regions", []),
        combo_bonus_after=data.get("combo_bonus_after", []),
    )


def load_badges(directory: Path | None = None) -> dict[str, dict]:
    """Load all badge definitions from JSON files.

    Args:
        directory: Directory containing badge JSON files.
                   Defaults to data/badges/.

    Returns:
        Dict of badge_id -> badge data dict.
    """
    if directory is None:
        directory = _DATA_DIR / "badges"

    registry: dict[str, dict] = {}

    if not directory.exists():
        logger.warning("Badges directory not found: %s", directory)
        return registry

    for path in sorted(directory.glob("*.json")):
        try:
            raw = _load_json(path)
            entries = raw if isinstance(raw, list) else [raw]
            for entry in entries:
                badge_id = entry["id"]
                if badge_id in registry:
                    logger.warning(
                        "Duplicate badge ID '%s' in %s (overwriting)",
                        badge_id,
                        path.name,
                    )
                registry[badge_id] = entry
        except Exception:
            logger.exception("Failed to load badges from %s", path)

    logger.info("Loaded %d badges from %s", len(registry), directory)
    return registry
