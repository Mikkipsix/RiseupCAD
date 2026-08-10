# -*- coding: utf-8 -*-
"""Smoke test for the real RiseupCAD recognition pipeline."""
from __future__ import annotations
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
TEST_IMAGE = ROOT / "testdata" / "riseupcad_test_01.jpeg"
OUT = ROOT / "out_e2e"
EXPECTED = [100, 100, 500, 500, 6000, 6000, 6000, 15000]


def main():
    if not TEST_IMAGE.exists():
        raise SystemExit(f"Missing test fixture: {TEST_IMAGE}")
    sys.path.insert(0, str(ROOT))
    from vector.pipeline import vectorize
    from vector.integration import export_recognition

    result = vectorize(str(TEST_IMAGE), dpi=300, do_ocr=True)
    numbers = result.get("numbers", [])
    got = sorted(int(n.value) for n in numbers)
    if got != sorted(EXPECTED):
        raise AssertionError(f"OCR mismatch: {got} != {sorted(EXPECTED)}")

    model, qa = export_recognition(
        result,
        OUT,
        dims=result.get("used_dims", []),
        scale=result.get("scale"),
        include_ocr_text=True,
        expected_numbers=EXPECTED,
        expected_dimensions=[d.value for d in result.get("used_dims", [])],
    )
    print("QA:", qa)
    print("Objects:", len(model.objects))
    print("Output:", OUT / "output.dxf")
    if not qa["ok"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
