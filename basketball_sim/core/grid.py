"""7x9 chess-style basketball court grid.

The half-court is divided into 63 cells (columns A-G, rows 1-9).
Each cell is ~7 feet wide by ~5 feet deep, roughly 1-2 dribbles.

    A      B      C      D      E      F      G
9  backcourt -------------------------------------------
8  halfcourt -------------------------------------------
7  above the arc ---------------------------------------
6  three-point line ------------------------------------
5  free throw extended ---------------------------------
4  elbow area ------------------------------------------
3  post / block ----------------------------------------
2  low baseline ----------------------------------------
1  under basket ----------------------------------------

The basket is at D1. Three-point line runs through row 6 (and corners
at A5/G5). The paint spans columns C-E, rows 1-4.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Column letters and row numbers
COLUMNS = "ABCDEFG"
ROWS = range(1, 10)  # 1-9

# Column index lookup
_COL_INDEX = {c: i for i, c in enumerate(COLUMNS)}


def _parse_cell(cell: str) -> tuple[int, int]:
    """Parse a cell label like 'B6' into (col_index, row_index)."""
    if len(cell) < 2 or cell[0] not in _COL_INDEX:
        raise ValueError(f"Invalid cell: {cell!r}")
    col = _COL_INDEX[cell[0]]
    row = int(cell[1:]) - 1  # zero-based row
    if row < 0 or row > 8:
        raise ValueError(f"Row out of range in cell: {cell!r}")
    return col, row


@dataclass(frozen=True)
class CellMetadata:
    """Basketball-relevant metadata for a single grid cell."""
    cell_id: str
    col: int  # 0-based column index
    row: int  # 0-based row index (0 = baseline row 1, 8 = backcourt row 9)
    is_three: bool
    is_corner_three: bool
    is_paint: bool
    is_restricted_area: bool
    is_post: bool
    is_midrange: bool
    is_backcourt: bool
    distance_to_basket: float  # approximate distance in feet
    region: str  # human-readable region name


def _build_cell(cell_id: str) -> CellMetadata:
    """Compute metadata for a single cell."""
    col, row = _parse_cell(cell_id)

    # Paint: columns C-E (indices 2-4), rows 1-4 (indices 0-3)
    is_paint = 2 <= col <= 4 and 0 <= row <= 3

    # Restricted area: columns C-E, rows 1-2 (indices 0-1)
    is_restricted = 2 <= col <= 4 and 0 <= row <= 1

    # Post: columns B-C or E-F, rows 2-3 (indices 1-2)
    is_post = (col in (1, 2, 4, 5)) and (1 <= row <= 2)

    # Backcourt: rows 8-9 (indices 7-8)
    is_backcourt = row >= 7

    # Three-point line geometry (approximate).
    # Corner threes: A5 / G5 only (far left / right, row label 5).
    is_corner_three = (col in (0, 6)) and (row == 4)

    # Arc threes: row label 6 inner columns (B6-F6) and all of row label 7
    # (above the arc), plus the outer columns on row 6 (A6, G6) which are
    # the long-corner / wing threes.
    is_arc_three = (
        (row == 5 and 1 <= col <= 5)
        or (row == 5 and col in (0, 6))
        or (row == 6)
    )

    is_three = is_corner_three or is_arc_three

    # Midrange: inside the arc but outside the paint, not backcourt
    is_midrange = (
        not is_three
        and not is_paint
        and not is_backcourt
        and not is_restricted
        and row <= 6
    )

    # Distance to basket (D1 = col 3, row 0) in approximate feet
    # Each cell is roughly 7 ft wide, 5.2 ft deep
    dx = (col - 3) * 7.0
    dy = row * 5.2
    distance = math.sqrt(dx * dx + dy * dy)

    # Region name
    if is_backcourt:
        region = "backcourt"
    elif is_restricted:
        region = "restricted_area"
    elif is_paint:
        region = "paint"
    elif is_post:
        region = "post"
    elif is_corner_three:
        region = "corner_three"
    elif is_three:
        region = "three_point"
    elif is_midrange:
        region = "midrange"
    else:
        region = "perimeter"

    return CellMetadata(
        cell_id=cell_id,
        col=col,
        row=row,
        is_three=is_three,
        is_corner_three=is_corner_three,
        is_paint=is_paint,
        is_restricted_area=is_restricted,
        is_post=is_post,
        is_midrange=is_midrange,
        is_backcourt=is_backcourt,
        distance_to_basket=round(distance, 1),
        region=region,
    )


# ---------------------------------------------------------------------------
# Grid singleton -- built once, reused everywhere
# ---------------------------------------------------------------------------

class CourtGrid:
    """The 7x9 basketball court grid with all cell metadata and utilities."""

    def __init__(self) -> None:
        self._cells: dict[str, CellMetadata] = {}
        for c in COLUMNS:
            for r in ROWS:
                cell_id = f"{c}{r}"
                self._cells[cell_id] = _build_cell(cell_id)

    @property
    def all_cells(self) -> dict[str, CellMetadata]:
        """All 63 cells keyed by cell_id."""
        return self._cells

    def get(self, cell_id: str) -> CellMetadata:
        """Look up metadata for a cell. Raises KeyError if invalid."""
        return self._cells[cell_id]

    def is_valid(self, cell_id: str) -> bool:
        """Check if a cell_id is valid."""
        return cell_id in self._cells

    def manhattan_distance(self, a: str, b: str) -> int:
        """Manhattan distance between two cells (in grid steps)."""
        ac, ar = _parse_cell(a)
        bc, br = _parse_cell(b)
        return abs(ac - bc) + abs(ar - br)

    def cells_between(self, a: str, b: str) -> list[str]:
        """Return cells along the line from a to b (Bresenham-style).

        Used for passing lane checks. Includes start and end cells.
        """
        ac, ar = _parse_cell(a)
        bc, br = _parse_cell(b)

        cells: list[str] = []
        dc = bc - ac
        dr = br - ar
        steps = max(abs(dc), abs(dr))
        if steps == 0:
            return [a]

        for i in range(steps + 1):
            t = i / steps
            col = round(ac + dc * t)
            row = round(ar + dr * t)
            cell_id = f"{COLUMNS[col]}{row + 1}"
            if not cells or cells[-1] != cell_id:
                cells.append(cell_id)

        return cells

    def cells_in_region(self, region: str) -> list[str]:
        """Return all cells belonging to a named region."""
        return [c.cell_id for c in self._cells.values() if c.region == region]

    def adjacent(self, cell_id: str) -> list[str]:
        """Return all cells within 1 step (including diagonals)."""
        col, row = _parse_cell(cell_id)
        result: list[str] = []
        for dc in (-1, 0, 1):
            for dr in (-1, 0, 1):
                if dc == 0 and dr == 0:
                    continue
                nc, nr = col + dc, row + dr
                if 0 <= nc < len(COLUMNS) and 0 <= nr < 9:
                    result.append(f"{COLUMNS[nc]}{nr + 1}")
        return result

    def __repr__(self) -> str:
        return f"CourtGrid(cells={len(self._cells)})"


# Module-level grid instance -- import and use this everywhere
COURT = CourtGrid()
