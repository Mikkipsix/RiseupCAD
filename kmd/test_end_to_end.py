# -*- coding: utf-8 -*-
"""End-to-end smoke test for the real RiseupCAD recognition pipeline."""
from __future__ import annotations
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
KMD = ROOT / "kmd"
TEST_IMAGE = ROOT / "testdata" / "riseupcad_test_01.jpeg"
OUT = ROOT / "out_e2e"
EXPECTED_NUMBERS = [100, 100, 500, 500, 6000, 6000, 6000, 15000]
EXPECTED_DIMS = [6000, 6000, 6000, 15000]


def main():
    if not TEST_IMAGE.exists():
        raise SystemExit(f"Missing test fixture: {TEST_IMAGE}")
    sys.path.insert(0, str(KMD))
    from vector.pipeline import vectorize
    from vector.integration import export_recognition

    result = vectorize(str(TEST_IMAGE), dpi=300, do_ocr=True)
    numbers = result.get("numbers", [])
    got = sorted(int(n.value) for n in numbers)
    print("OCR raw:", got)

    # OCR is intentionally allowed to return false positives. The real
    # contract is that dimension pairing/geometry must reject them rather
    # than making the whole pipeline fail before it reaches that stage.
    missing_expected = sorted(set(EXPECTED_NUMBERS) - set(got))
    if missing_expected:
        raise AssertionError(
            f"OCR missed expected values: {missing_expected}; got {got}"
        )

    used_dims = result.get("used_dims", [])
    used_values = sorted(int(d.value) for d in used_dims)
    if used_values != sorted(EXPECTED_DIMS):
        raise AssertionError(
            f"Dimension mismatch: {used_values} != {sorted(EXPECTED_DIMS)}"
        )

    model, qa = export_recognition(
        result,
        OUT,
        dims=used_dims,
        scale=result.get("scale"),
        include_ocr_text=True,
        expected_numbers=EXPECTED_NUMBERS,
        expected_dimensions=EXPECTED_DIMS,
    )
    print("QA:", qa)
    print("OCR:", got)
    print("Dimensions:", used_values)
    print("Objects:", len(model.objects))
    print("Output:", OUT / "output.dxf")
    if not qa["ok"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
