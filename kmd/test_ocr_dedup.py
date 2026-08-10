from vector.solve import Num
from vector.ocr_dedup import dedup_numbers


def test_repeated_ocr_detection_keeps_best_confidence():
    nums = [
        Num(6000, 673.0, 1561.5, 58.0, 27.0, 96.0, False),
        Num(6000, 671.9, 1546.0, 56.2, 58.0, 40.0, False),
        Num(6000, 1200.0, 100.0, 58.0, 27.0, 90.0, False),
    ]
    got = dedup_numbers(nums)
    assert len(got) == 2
    assert sorted(n.conf for n in got) == [90.0, 96.0]


def test_distinct_nearby_labels_are_preserved():
    nums = [
        Num(500, 100.0, 100.0, 40.0, 20.0, 95.0, False),
        Num(500, 150.0, 100.0, 40.0, 20.0, 94.0, False),
    ]
    assert len(dedup_numbers(nums)) == 2


def test_different_values_are_never_deduplicated():
    nums = [
        Num(6000, 100.0, 100.0, 60.0, 25.0, 95.0, False),
        Num(500, 100.0, 100.0, 60.0, 25.0, 94.0, False),
    ]
    assert len(dedup_numbers(nums)) == 2
