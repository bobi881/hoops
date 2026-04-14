"""Tests for the chess-style court grid."""

import pytest

from basketball_sim.core.grid import COURT, CourtGrid, _parse_cell


def test_grid_has_63_cells():
    assert len(COURT.all_cells) == 63


def test_parse_cell_valid():
    assert _parse_cell("A1") == (0, 0)
    assert _parse_cell("D1") == (3, 0)
    assert _parse_cell("G9") == (6, 8)


def test_parse_cell_invalid():
    with pytest.raises(ValueError):
        _parse_cell("Z1")
    with pytest.raises(ValueError):
        _parse_cell("A0")
    with pytest.raises(ValueError):
        _parse_cell("")


def test_basket_cell_is_restricted():
    d1 = COURT.get("D1")
    assert d1.is_restricted_area
    assert d1.is_paint
    assert d1.distance_to_basket == 0.0


def test_corner_three():
    a5 = COURT.get("A5")
    assert a5.is_three
    assert a5.is_corner_three
    assert a5.region == "corner_three"

    g5 = COURT.get("G5")
    assert g5.is_three
    assert g5.is_corner_three


def test_arc_three():
    d6 = COURT.get("D6")
    assert d6.is_three
    assert not d6.is_corner_three
    assert d6.region == "three_point"


def test_paint_cells():
    for cell_id in ["C1", "C2", "C3", "C4", "D1", "D2", "D3", "D4", "E1", "E2", "E3", "E4"]:
        cell = COURT.get(cell_id)
        assert cell.is_paint, f"{cell_id} should be in the paint"


def test_backcourt():
    for cell_id in ["A8", "D8", "G8", "A9", "D9", "G9"]:
        cell = COURT.get(cell_id)
        assert cell.is_backcourt, f"{cell_id} should be backcourt"

    assert not COURT.get("D7").is_backcourt


def test_manhattan_distance():
    assert COURT.manhattan_distance("A1", "A1") == 0
    assert COURT.manhattan_distance("A1", "B1") == 1
    assert COURT.manhattan_distance("A1", "G9") == 14  # 6 + 8
    assert COURT.manhattan_distance("D1", "D6") == 5


def test_cells_between():
    lane = COURT.cells_between("A6", "G6")
    assert lane[0] == "A6"
    assert lane[-1] == "G6"
    assert len(lane) == 7  # straight horizontal line

    lane_vert = COURT.cells_between("D1", "D6")
    assert lane_vert[0] == "D1"
    assert lane_vert[-1] == "D6"


def test_cells_between_same_cell():
    lane = COURT.cells_between("D5", "D5")
    assert lane == ["D5"]


def test_adjacent():
    adj = COURT.adjacent("D5")
    # D5 is in the middle, should have 8 neighbors
    assert len(adj) == 8
    assert "C4" in adj
    assert "E6" in adj
    assert "D5" not in adj  # self excluded

    # Corner cell: A1 should have 3 neighbors
    adj_corner = COURT.adjacent("A1")
    assert len(adj_corner) == 3
    assert "A2" in adj_corner
    assert "B1" in adj_corner
    assert "B2" in adj_corner


def test_cells_in_region():
    paint_cells = COURT.cells_in_region("paint")
    assert len(paint_cells) > 0
    for cell_id in paint_cells:
        assert COURT.get(cell_id).is_paint

    backcourt_cells = COURT.cells_in_region("backcourt")
    assert len(backcourt_cells) > 0


def test_is_valid():
    assert COURT.is_valid("A1")
    assert COURT.is_valid("G9")
    assert not COURT.is_valid("H1")
    assert not COURT.is_valid("A0")
    assert not COURT.is_valid("")


def test_distance_increases_away_from_basket():
    d1 = COURT.get("D1")
    d5 = COURT.get("D5")
    d9 = COURT.get("D9")
    assert d1.distance_to_basket < d5.distance_to_basket < d9.distance_to_basket
