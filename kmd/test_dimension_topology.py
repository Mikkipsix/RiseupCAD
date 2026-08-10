from types import SimpleNamespace

from vector.dimension_topology import build_dimension_topology
from vector.solve import Dim, Num


def seg(kind, x1, y1, x2, y2, role="thin"):
    return SimpleNamespace(
        kind=kind, x1=x1, y1=y1, x2=x2, y2=y2,
        role=role, length=((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5,
    )


def test_horizontal_dimension_links_vertical_witnesses():
    dims = [Dim(500, False, 100, 139, 50,
                Num(500, 119.5, 50, 27, 12, 90, False))]
    segs = [seg("v", 100, 20, 100, 80), seg("v", 139, 20, 139, 80)]
    topo = build_dimension_topology(dims, segs, scale=500 / 39)
    assert topo[0]["object_a"] == 0
    assert topo[0]["object_b"] == 1
    assert topo[0]["target_px"] > 38
    assert topo[0]["confidence"] > 0.9


def test_vertical_dimension_links_horizontal_witnesses():
    dims = [Dim(100, True, 10, 18, 40,
                Num(100, 40, 14, 10, 27, 82, True))]
    segs = [seg("h", 0, 10, 80, 10), seg("h", 0, 18, 80, 18)]
    topo = build_dimension_topology(dims, segs, scale=100 / 8)
    assert topo[0]["object_a"] == 0
    assert topo[0]["object_b"] == 1
    assert topo[0]["orientation"] == "vertical"


def test_missing_witness_is_explicit():
    dims = [Dim(6000, False, 100, 568, 50)]
    segs = [seg("v", 100, 20, 100, 80)]
    topo = build_dimension_topology(dims, segs, scale=6000 / 468)
    assert topo[0]["object_a"] == 0
    assert topo[0]["object_b"] is None
    assert topo[0]["confidence"] < 0.7
