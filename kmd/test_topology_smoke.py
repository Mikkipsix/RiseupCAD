from vector.dimension_topology import build_dimension_topology


def test_topology_output_is_json_friendly():
    class S:
        kind = "v"
        x1, y1, x2, y2 = 100.0, 0.0, 100.0, 100.0
        role = "thin"
        length = 100.0

    class N:
        value, vertical, a, b, line = 100, False, 100, 108, 50
        num = None

    result = build_dimension_topology([N()], [S()], scale=12.5)
    assert isinstance(result, list)
    assert set(result[0]) >= {"value", "span_px", "target_px", "object_a", "object_b", "confidence"}
