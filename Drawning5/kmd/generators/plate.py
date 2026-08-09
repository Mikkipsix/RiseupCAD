# -*- coding: utf-8 -*-
"""Деталировка полосы с отверстиями (поз.14 и подобные)."""
from ezdxf.enums import TextEntityAlignment as TA

from gostcad import new_doc
from gostcad.draw import dim_h, dim_v, polka, text

TH = 5.0


def build(spec, path, title):
    L = float(spec["length"])
    B = float(spec["strip"]["b"])
    holes = spec.get("holes", [])

    doc = new_doc(text_h=TH, ltscale=4.0)
    msp = doc.modelspace()

    # контур
    msp.add_lwpolyline([(0, 0), (L, 0), (L, B), (0, B)],
                       format="xy", close=True, dxfattribs={"layer": "OUTLINE"})

    expected = [L, B]

    # продольная ось
    msp.add_line((-10, B / 2), (L + 10, B / 2), dxfattribs={"layer": "CENTER"})

    for h in holes:
        x, y, d = float(h["x"]), float(h["y"]), float(h["d"])
        msp.add_circle((x, y), d / 2, dxfattribs={"layer": "OUTLINE"})
        # осевая доведена ниже размерной линии: служит выносной
        msp.add_line((x, -18.0), (x, y + d / 2 + 4),
                     dxfattribs={"layer": "CENTER"})
        # привязка отверстия к ближней кромке; обе выносные подавлены -
        # слева их роль играет осевая, справа - выносная габарита
        near_right = (L - x) <= x
        p2 = (L, 0.0) if near_right else (0.0, 0.0)
        dim_h(msp, (x, y), p2, -14.0, se1=True, se2=True)
        expected.append(abs(L - x) if near_right else x)
        polka(msp, (x + d / 2 * 0.71, y + d / 2 * 0.71),
              (L * 0.42, B + 40.0), f"Отв. \u2300{d:g}", TH)

    # габариты
    dim_h(msp, (0, 0), (L, 0), -28.0)
    dim_v(msp, (0, 0), (0, B), -14.0)

    text(msp, title, L / 2, B + 62.0, 10.0, TA.MIDDLE_CENTER)
    st = spec["strip"]
    text(msp, f'Полоса {st["t"]:g}x{st["b"]:g} {st["gost"]}, {st["steel"]}',
         L / 2, -48.0, TH, TA.MIDDLE_CENTER)

    doc.set_modelspace_vport(height=B * 5, center=(L / 2, B / 2))
    doc.saveas(path)
    return sorted(expected)
