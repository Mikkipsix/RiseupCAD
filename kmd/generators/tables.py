# -*- coding: utf-8 -*-
"""Ведомость деталей и спецификации - из общего табличного движка."""
from ezdxf.enums import TextEntityAlignment as TA

from gostcad import Table, new_doc
from gostcad.calc import fmt_kg
from gostcad.draw import text

POS, OBZ, NAM, KOL, MAS, PRM = 0, 1, 2, 3, 4, 5


# =====================================================================
#  ВЕДОМОСТЬ ДЕТАЛЕЙ (схематичные эскизы, вне масштаба)
# =====================================================================
def vedomost(hoops, bent, path):
    items = sorted(hoops["items"].items(), key=lambda kv: int(kv[0]))
    n = len(items) + 1

    doc = new_doc(text_h=3.0, ltscale=0.5)
    msp = doc.modelspace()
    t = Table([(20.0, "Поз."), (110.0, "Эскиз")], n_rows=n,
              row_h=28.0, head_h=14.0, text_h=3.0)

    S, TAIL, THN = 13.0, 4.0, 3.0
    xc = t.col_mid(1)

    for i, (pos, ab) in enumerate(items, start=1):
        a, b = float(ab[0]), float(ab[1])
        yc = t.row_mid(i)
        text(msp, str(pos), t.col_mid(0), yc, 5.0)
        x0, y0 = xc - S / 2, yc - S / 2
        x1, y1 = x0 + S, y0 + S
        # гнутый контур: конец верхней грани -> угол -> левая -> низ -> правая
        msp.add_lwpolyline(
            [(x1 + TAIL, y1), (x0, y1), (x0, y0), (x1, y0), (x1, y1 + TAIL)],
            format="xy", close=False, dxfattribs={"layer": "SKETCH"})
        text(msp, f"{b:g}", xc - 1, y1 + 1, THN, TA.BOTTOM_CENTER)
        text(msp, f"{a:g}", xc, y0 - 1, THN, TA.TOP_CENTER)
        text(msp, f"{a:g}", x0 - 1.5, yc, THN, TA.MIDDLE_RIGHT)
        text(msp, f"{b:g}", x1 + TAIL + 1.5, yc, THN, TA.MIDDLE_LEFT)

    # поз.13
    yc = t.row_mid(n)
    text(msp, "13", t.col_mid(0), yc, 5.0)
    kx, ky = xc - 35.0, yc + 2.0
    ex, ey = kx + 62.0, ky - 6.5
    msp.add_lwpolyline([(kx, ky + 11.0), (kx, ky), (ex, ey)],
                       format="xy", close=False, dxfattribs={"layer": "SKETCH"})
    msp.add_line((kx, ky), (ex + 4.0, ky), dxfattribs={"layer": "CENTER"})
    s1, s2 = bent["segments"]
    text(msp, f"{s1:g}", kx - 1.5, ky + 5.5, THN, TA.MIDDLE_RIGHT)
    text(msp, f"{s2:g}", kx + 30.0, ky - 5.0, THN, TA.TOP_CENTER)
    text(msp, f'{bent["drop"]:g}', ex + 6.0, ey, THN, TA.MIDDLE_LEFT)

    t.render(msp)
    text(msp, "Ведомость деталей", t.w / 2, t.h + 4.0, 6.0, TA.BOTTOM_CENTER)
    doc.set_modelspace_vport(height=t.h * 1.2, center=(t.w / 2, t.h / 2))
    doc.saveas(path)
    return t.warnings


# =====================================================================
#  СПЕЦИФИКАЦИЯ ЗАКЛАДНОЙ ДЕТАЛИ (короткая форма)
# =====================================================================
def spec_zd1(plate, anchor, m15, m16, path, title):
    doc = new_doc(text_h=3.5, ltscale=1.0)
    msp = doc.modelspace()
    t = Table([(20.0, "Поз."), (100.0, "Наименование"), (15.0, "Кол."),
               (17.0, ["Масса", "ед.,", "кг"])],
              n_rows=3, row_h=8.0, head_h=16.0, text_h=3.5)

    t.cell(1, 0, "15").cell(1, 2, str(plate["qty"])).cell(1, 3, fmt_kg(m15))
    st = plate["strip"]
    t.fraction(1, 1, f'{st["t"]:g}x{st["b"]:g} {st["gost"]}',
               f'{st["steel"]} {st["steel_gost"]}',
               prefix="Полоса", suffix=f'L={plate["length"]:g}',
               bar=(18.0, 72.0))
    b = anchor["bar"]
    t.cell(3, 0, "16")
    t.cell(3, 1, f'{b["d"]:g}{b["cls"]}  l={anchor["length"]:g}', "l")
    t.cell(3, 2, str(anchor["qty"])).cell(3, 3, fmt_kg(m16))

    t.render(msp)
    text(msp, title, t.w / 2, t.h + 4.0, 5.0, TA.BOTTOM_CENTER)
    doc.set_modelspace_vport(height=t.h * 1.8, center=(t.w / 2, t.h / 2))
    doc.saveas(path)
    return t.warnings


# =====================================================================
#  ОБЩАЯ СПЕЦИФИКАЦИЯ
# =====================================================================
def spec_main(data, calc_mass, calc_len, path):
    P = data["parts"]
    hp = P["hoops"]
    items = sorted(hp["items"].items(), key=lambda kv: int(kv[0]))

    doc = new_doc(text_h=3.5, ltscale=1.0)
    msp = doc.modelspace()
    t = Table([(15.0, "Поз."), (50.0, "Обозначение"), (72.0, "Наименование"),
               (12.0, "Кол."), (16.0, ["Масса", "ед., кг"]),
               (20.0, ["Приме-", "чание"])],
              n_rows=25, row_h=8.0, head_h=16.0, text_h=3.5)

    t.underline(1, NAM, "Сборочные единицы")
    t.cell(2, NAM, P[1]["subsection"])
    # поз.1 - дробь сетки в объединённой ячейке строк 3-4
    t.cell(3, POS, "1").cell(3, OBZ, P[1]["designation"])
    f = P[1]["name_fraction"]
    t.fraction(NAM, 3, f["top"], f["bottom"], prefix=f["prefix"],
               suffix=f["suffix"], bar=(19.0, 43.0))
    t.cell(4, KOL, str(P[1]["qty"])).cell(4, MAS, P[1]["mass_ref"])

    t.cell(5, NAM, P[2]["subsection"])
    t.cell(6, POS, "2").cell(6, OBZ, P[2]["designation"])
    t.cell(6, NAM, P[2]["name_lines"][0])
    t.cell(7, NAM, P[2]["name_lines"][1])
    t.cell(7, KOL, str(P[2]["qty"])).cell(7, MAS, P[2]["mass_ref"])

    b3 = P[3]["bar"]
    t.cell(8, POS, "3")
    t.cell(8, NAM, f'{b3["d"]:g}{b3["cls"]} {b3["gost"]} L={calc_len[3]:.0f}')
    t.cell(8, KOL, str(P[3]["qty"])).cell(8, MAS, fmt_kg(calc_mass[3]))

    t.cell(9, POS, "4").cell(9, OBZ, P[4]["designation"])
    t.cell(9, NAM, P[4]["name"])
    t.cell(9, KOL, str(P[4]["qty"])).cell(9, MAS, fmt_kg(calc_mass[4]))

    t.underline(10, NAM, "Детали")
    t.cell(11, NAM, hp["header"])
    t.merged_text(OBZ, 11, 20, hp["designation_merged"])

    for i, (pos, _ab) in enumerate(items):
        r = 12 + i
        t.cell(r, POS, str(pos))
        t.cell(r, NAM, f"L={calc_len[int(pos)]:.0f}")
        t.cell(r, KOL, str(hp["qty_each"]))
        t.cell(r, MAS, fmt_kg(calc_mass[int(pos)]))

    b13 = P[13]["bar"]
    t.cell(20, POS, "13")
    t.cell(20, NAM, f'{b13["d"]:g}{b13["cls"]} {b13["gost"]} L={calc_len[13]:.0f}')
    t.cell(20, KOL, str(P[13]["qty"])).cell(20, MAS, fmt_kg(calc_mass[13]))

    st = P[14]["strip"]
    t.cell(21, POS, "14")
    t.fraction(NAM, 21, f'{st["t"]:g}x{st["b"]:g} {st["gost"]}',
               f'{st["steel"]} {st["steel_gost"]}',
               prefix="Полоса", bar=None, merge_cell=False)
    t.cell(23, NAM, f'L={P[14]["length"]:g}')
    t.cell(23, KOL, str(P[14]["qty"])).cell(23, MAS, fmt_kg(calc_mass[14]))

    t.underline(24, NAM, "Материалы")
    conc = data["materials"]["concrete"]
    t.cell(25, NAM, conc["name"]).cell(25, PRM, conc["volume"])

    t.render(msp)
    doc.set_modelspace_vport(height=t.h * 1.15, center=(t.w / 2, t.h / 2))
    doc.saveas(path)
    return t.warnings
