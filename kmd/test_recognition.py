# -*- coding: utf-8 -*-
"""
Сравнение распознавания с эталоном.

Эталон - чертежи, построенные вручную по тем же исходникам. Проверяется
не «похоже ли», а инженерные величины: габарит замкнутого контура,
диаметры и положения отверстий, набор значений DIMENSION.

    python3 test_recognition.py
"""
import math
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ezdxf                                          # noqa: E402
from ezdxf.audit import Auditor                       # noqa: E402

from vector import raster                             # noqa: E402

UP = "/mnt/user-data/uploads"

CASES = [
    {
        "name": "поз.14  полоса 150x50 с отверстием",
        "file": f"{UP}/1785906665769_image.png",
        "contour": (150.0, 50.0),
        "holes": [(100.0, 25.0, 10.0)],
        "dims": [150, 50, 50],
    },
    {
        "name": "ЗД1  закладная деталь",
        "file": f"{UP}/1785909933131_image.png",
        "contour": (50.0, 300.0),
        "holes": [(25.0, 280.0, 8.0), (25.0, 20.0, 8.0)],
        "dims": [300, 260, 50, 25, 20, 206],
    },
    {
        "name": "поз.3  подвеска (гнутая, только дуги)",
        "file": f"{UP}/1785907532659_image.png",
        "contour": None,
        "holes": [],
        "dims": [490],
        "arcs": [33.0, 47.0],          # радиусы гибов: внутренний и наружный
    },
]

TOL_MM = 1.0
TOL_D = 1.5


def measure(path):
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    aud = Auditor(doc)
    aud.run()
    out = {"audit": len(aud.errors),
           "ents": dict(Counter(e.dxftype() for e in msp)),
           "layers": dict(Counter(e.dxf.layer for e in msp)),
           "dims": sorted(round(d.get_measurement(), 1)
                          for d in msp.query("DIMENSION")),
           "circles": [(round(c.dxf.center.x, 1), round(c.dxf.center.y, 1),
                        round(2 * c.dxf.radius, 1))
                       for c in msp.query("CIRCLE")],
           "arcs": sorted(round(a.dxf.radius, 1) for a in msp.query("ARC")),
           "polys": []}
    for pl in msp.query("LWPOLYLINE"):
        pts = list(pl.get_points("xy"))
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        out["polys"].append((round(max(xs) - min(xs), 1),
                             round(max(ys) - min(ys), 1),
                             round(min(xs), 1), round(min(ys), 1), pl.closed))
    return out


def check(case, m):
    ok, notes = True, []

    if case["contour"]:
        w, h = case["contour"]
        hit = [p for p in m["polys"]
               if abs(p[0] - w) <= TOL_MM and abs(p[1] - h) <= TOL_MM
               or abs(p[0] - h) <= TOL_MM and abs(p[1] - w) <= TOL_MM]
        if hit:
            notes.append(f'контур {w:g}x{h:g}: НАЙДЕН '
                         f'({hit[0][0]:g}x{hit[0][1]:g}, замкнут={hit[0][4]})')
        else:
            ok = False
            got = ", ".join(f"{p[0]:g}x{p[1]:g}" for p in m["polys"]) or "нет"
            notes.append(f'контур {w:g}x{h:g}: НЕ НАЙДЕН (есть: {got})')

    if case["holes"]:
        base = None
        for p in m["polys"]:
            if base is None or p[0] * p[1] > base[0] * base[1]:
                base = p
        found = 0
        for hx, hy, hd in case["holes"]:
            best = None
            for cx, cy, cd in m["circles"]:
                if base:
                    lx, ly = cx - base[2], cy - base[3]
                else:
                    lx, ly = cx, cy
                e = math.hypot(lx - hx, ly - hy) + abs(cd - hd)
                if best is None or e < best[0]:
                    best = (e, lx, ly, cd)
            if best and abs(best[3] - hd) <= TOL_D and \
                    math.hypot(best[1] - hx, best[2] - hy) <= 4 * TOL_MM:
                found += 1
                notes.append(f'отверстие ⌀{hd:g} в ({hx:g},{hy:g}): НАЙДЕНО '
                             f'⌀{best[3]:g} в ({best[1]:.1f},{best[2]:.1f})')
            else:
                ok = False
                notes.append(f'отверстие ⌀{hd:g} в ({hx:g},{hy:g}): нет '
                             f'(ближайшее {best[3] if best else "-"})')
        if found != len(case["holes"]):
            ok = False
        if len(m["circles"]) > len(case["holes"]):
            notes.append(f'лишних окружностей: '
                         f'{len(m["circles"]) - len(case["holes"])}')

    for r in case.get("arcs", []):
        hit = [a for a in m["arcs"] if abs(a - r) <= 3.0]
        if hit:
            notes.append(f'дуга R{r:g}: НАЙДЕНА R{hit[0]:g}')
        else:
            ok = False
            notes.append(f'дуга R{r:g}: нет (есть {m["arcs"]})')

    want = Counter(case["dims"])
    got = Counter(int(round(v)) for v in m["dims"])
    hit = sorted((want & got).elements())
    miss = sorted((want - got).elements())
    extra = sorted((got - want).elements())
    notes.append(f'размеры: найдено {hit}, пропущено {miss}'
                 + (f', лишних {extra}' if extra else ""))
    if not hit:
        ok = False

    if m["audit"]:
        ok = False
        notes.append(f'АУДИТ: {m["audit"]} ошибок')
    return ok, notes


def main():
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "out_recog")
    os.makedirs(out_dir, exist_ok=True)
    total_ok = True
    print("=" * 74)
    print("СРАВНЕНИЕ РАСПОЗНАВАНИЯ С РУЧНЫМ ЭТАЛОНОМ")
    print("=" * 74)
    for case in CASES:
        if not os.path.exists(case["file"]):
            print(f'\n{case["name"]}: файл не найден, пропуск')
            continue
        res = raster.vectorize(case["file"])
        dxf = os.path.join(out_dir, os.path.basename(case["file"]) + ".dxf")
        raster.to_dxf(res, dxf)
        m = measure(dxf)
        ok, notes = check(case, m)
        total_ok &= ok
        print(f'\n[{"OK" if ok else "ЧАСТИЧНО"}] {case["name"]}')
        print(f'    масштаб {res["scale"]:.4f} мм/px  ({res["scale_source"]})')
        print(f'    объекты: {m["ents"]}')
        print(f'    слои: {m["layers"]}')
        for n in notes:
            print(f'    {n}')
    print("\n" + "=" * 74)
    print("Итог:", "все контрольные величины совпали" if total_ok
          else "часть величин не совпала, подробности выше")
    return 0 if total_ok else 1


if __name__ == "__main__":
    sys.exit(main())
