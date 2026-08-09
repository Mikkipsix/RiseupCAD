#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сборка комплекта из parts.yaml одной командой.

Этапы: расчёт развёрток и масс -> сверка с бумажной спецификацией ->
генерация DXF -> обязательный аудит. Ненулевой код возврата, если хоть
один файл не прошёл аудит.
"""
import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gostcad import calc, validate                       # noqa: E402
from generators import embed, hook, plate, tables        # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "out")
TOL_MASS = 0.02          # кг, допуск сверки с бумажной спецификацией
TOL_LEN = 2.0            # мм


def parse_kg(s):
    return float(str(s).replace(",", "."))


def main():
    with open(os.path.join(ROOT, "parts.yaml"), encoding="utf-8") as f:
        data = yaml.safe_load(f)
    P = data["parts"]
    os.makedirs(OUT, exist_ok=True)

    mass, length, diverge = {}, {}, []

    # ---------- расчёт ----------
    hp = P["hoops"]
    d_h = float(hp["bar"]["d"])
    for pos, ab in hp["items"].items():
        pos = int(pos)
        L = calc.hoop_development(float(ab[0]), float(ab[1]))
        length[pos] = L
        mass[pos] = calc.bar_mass(d_h, L)

    b13 = P[13]
    length[13] = calc.bent_development(b13["segments"])
    mass[13] = calc.bar_mass(float(b13["bar"]["d"]), length[13])

    p14 = P[14]
    holes = () if p14.get("mass_ignores_holes") else \
        [float(h["d"]) for h in p14.get("holes", [])]
    mass[14] = calc.plate_mass(float(p14["strip"]["t"]), float(p14["strip"]["b"]),
                               float(p14["length"]), holes)

    p15 = P[15]
    mass[15] = calc.plate_mass(float(p15["strip"]["t"]), float(p15["strip"]["b"]),
                               float(p15["length"]))
    p16 = P[16]
    mass[16] = calc.bar_mass(float(p16["bar"]["d"]), float(p16["length"]))
    mass[4] = mass[15] * int(p15["qty"]) + mass[16] * int(p16["qty"])

    p3 = P[3]
    length[3] = calc.hook_development(float(p3["height"]), float(p3["leg"]),
                                      float(p3["r_axis"]), float(p3["bar"]["d"]))
    mass[3] = calc.bar_mass(float(p3["bar"]["d"]), length[3])

    # ---------- сверка с бумажной спецификацией ----------
    print("=" * 74)
    print("СВЕРКА РАСЧЁТА С ИСХОДНОЙ СПЕЦИФИКАЦИЕЙ")
    print("=" * 74)
    print(f'{"поз":>5} {"L расч":>9} {"L спец":>8} {"m расч":>8} '
          f'{"m спец":>8}  статус')

    refs = {}
    for pos in hp["items"]:
        refs[int(pos)] = (hp["length_ref"].get(int(pos)),
                          hp["mass_ref"].get(int(pos)))
    for pos in (3, 4, 13, 14, 15, 16):
        refs[pos] = (P[pos].get("length_ref"), P[pos].get("mass_ref"))

    for pos in sorted(refs):
        lref, mref = refs[pos]
        lc = length.get(pos)
        mc = mass.get(pos)
        bad = []
        if lref is not None and lc is not None and abs(lc - float(lref)) > TOL_LEN:
            bad.append(f"ΔL={lc - float(lref):+.0f}")
        if mref is not None and abs(mc - parse_kg(mref)) > TOL_MASS:
            bad.append(f"Δm={mc - parse_kg(mref):+.2f}")
        st = "OK" if not bad else "!! " + " ".join(bad)
        if bad:
            diverge.append((pos, st))
        print(f'{pos:>5} {("-" if lc is None else f"{lc:.1f}"):>9} '
              f'{("-" if lref is None else str(lref)):>8} '
              f'{mc:>8.3f} {str(mref):>8}  {st}')

    # ---------- генерация ----------
    print()
    print("=" * 74)
    print("ГЕНЕРАЦИЯ И АУДИТ")
    print("=" * 74)
    reports, warns = [], []

    f14 = os.path.join(OUT, "poz_14_polosa.dxf")
    exp = plate.build(P[14], f14, "Поз.14")
    reports.append(validate.check(f14, expected_dims=exp, name="поз.14 полоса"))

    f4 = os.path.join(OUT, "poz_04_ZD1.dxf")
    exp = embed.build(P[15], P[16], f4, "Закладная деталь ЗД1")
    reports.append(validate.check(f4, expected_dims=exp, allow_overlap=2.0,
                                  name="поз.4 ЗД1"))

    f3 = os.path.join(OUT, "poz_03_podveska.dxf")
    exp, dev, step = hook.build(P[3], f3, "Поз.3")
    reports.append(validate.check(f3, expected_dims=exp, name="поз.3 подвеска"))

    f_v = os.path.join(OUT, "vedomost_detaley.dxf")
    warns += tables.vedomost(hp, P[13], f_v)
    reports.append(validate.check(f_v, name="ведомость деталей"))

    f_s1 = os.path.join(OUT, "specifikaciya_ZD1.dxf")
    warns += tables.spec_zd1(P[15], P[16], mass[15], mass[16], f_s1,
                             "Спецификация закладной детали ЗД1")
    reports.append(validate.check(f_s1, name="спецификация ЗД1"))

    f_s2 = os.path.join(OUT, "specifikaciya_obshchaya.dxf")
    warns += tables.spec_main(data, mass, length, f_s2)
    reports.append(validate.check(f_s2, name="спецификация общая"))

    for r in reports:
        print(r)

    # ---------- итог ----------
    print()
    print("=" * 74)
    failed = [r.name for r in reports if not r.ok]
    if warns:
        print("ПРЕДУПРЕЖДЕНИЯ ПО ШИРИНЕ ГРАФ:")
        for w in sorted(set(warns)):
            print("   ", w)
    if diverge:
        print("РАСХОЖДЕНИЯ С ИСХОДНОЙ СПЕЦИФИКАЦИЕЙ:")
        for pos, st in diverge:
            print(f"    поз.{pos}: {st}")
    if failed:
        print(f"АУДИТ НЕ ПРОЙДЕН: {', '.join(failed)}")
        return 1
    print(f"Все {len(reports)} файла прошли аудит. Каталог: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
