# -*- coding: utf-8 -*-
"""
Проверка сшивки дуг и прямых на синтетическом чертеже.

Рисуется прямоугольник со скруглёнными углами с точно известными
размерами, прогоняется через конвейер и сверяется: должен получиться
один замкнутый контур, в котором скругления представлены выпуклостью
(bulge), а не ломаной.

    python3 test_arcs.py
"""
import math
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ezdxf                                        # noqa: E402
from vector import raster                           # noqa: E402

W, H = 900, 600
X0, Y0, X1, Y1 = 150, 150, 750, 450      # прямоугольник 600 x 300 px
R = 80                                   # радиус скругления, px
SCALE = 0.5                              # мм/px -> деталь 300 x 150 мм
THICK = 3


def draw():
    img = np.full((H, W), 255, np.uint8)
    cv2.line(img, (X0 + R, Y0), (X1 - R, Y0), 0, THICK)
    cv2.line(img, (X0 + R, Y1), (X1 - R, Y1), 0, THICK)
    cv2.line(img, (X0, Y0 + R), (X0, Y1 - R), 0, THICK)
    cv2.line(img, (X1, Y0 + R), (X1, Y1 - R), 0, THICK)
    for cx, cy, a0, a1 in ((X0 + R, Y0 + R, 180, 270),
                           (X1 - R, Y0 + R, 270, 360),
                           (X1 - R, Y1 - R, 0, 90),
                           (X0 + R, Y1 - R, 90, 180)):
        cv2.ellipse(img, (cx, cy), (R, R), 0, a0, a1, 0, THICK)
    return img


def main():
    src = "/tmp/_arc_case.png"
    cv2.imwrite(src, draw())

    res = raster.vectorize(src, do_ocr=False, scale_override=SCALE)
    dxf = "/tmp/_arc_case.dxf"
    raster.to_dxf(res, dxf)

    doc = ezdxf.readfile(dxf)
    msp = doc.modelspace()
    polys = list(msp.query("LWPOLYLINE"))
    arcs = list(msp.query("ARC"))

    print(f"дуг найдено детектором: {len(res['arcs'])}")
    print(f"в DXF: полилиний {len(polys)}, отдельных ARC {len(arcs)}")

    ok = True
    if not polys:
        print("ОШИБКА: замкнутый контур не собран")
        return 1

    pl = max(polys, key=lambda p: len(p))
    pts = list(pl.get_points("xyb"))
    bulges = [p[2] for p in pts if abs(p[2]) > 1e-9]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    w_mm = (X1 - X0) * SCALE
    h_mm = (Y1 - Y0) * SCALE
    got_w, got_h = max(xs) - min(xs), max(ys) - min(ys)

    print(f"контур: вершин {len(pts)}, замкнут={pl.closed}, "
          f"дуговых сегментов {len(bulges)}")
    print(f"габарит: {got_w:.1f} x {got_h:.1f} мм  (эталон "
          f"{w_mm:.1f} x {h_mm:.1f})")

    if abs(got_w - w_mm) > 3.0 or abs(got_h - h_mm) > 3.0:
        print("ОШИБКА: габарит не сошёлся")
        ok = False
    if len(bulges) < 4:
        print(f"ОШИБКА: скруглений в полилинии {len(bulges)}, ожидалось 4")
        ok = False
    else:
        for b in bulges:
            sweep = math.degrees(4 * math.atan(abs(b)))
            if abs(sweep - 90.0) > 15.0:
                print(f"ОШИБКА: размах скругления {sweep:.1f}°, ожидалось 90°")
                ok = False
                break
        else:
            sw = [math.degrees(4 * math.atan(abs(b))) for b in bulges]
            print("размах скруглений: "
                  + ", ".join(f"{s:.1f}°" for s in sw))

    # площадь с учётом скруглений
    area = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i][0], pts[i][1]
        x2, y2 = pts[(i + 1) % len(pts)][0], pts[(i + 1) % len(pts)][1]
        area += x1 * y2 - x2 * y1
    area = abs(area) / 2.0
    r_mm = R * SCALE
    exact = w_mm * h_mm - (4 - math.pi) * r_mm * r_mm
    print(f"площадь по вершинам {area:.0f} мм², точная со скруглениями "
          f"{exact:.0f} мм²")

    print("\nИтог:", "сшивка работает" if ok else "есть расхождения")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
