# -*- coding: utf-8 -*-
"""
Оформление по ГОСТ 2.303 / 2.304 / 2.307: слои, текстовый стиль, размерные стили.
Один вызов new_doc() даёт готовый к работе документ.
"""
import ezdxf

TEXT_STYLE = "GOST_A"

# имя, цвет, тип линии, толщина (сотые мм)
LAYERS = [
    ("OUTLINE",    7, "CONTINUOUS", 60),   # основная линия видимого контура
    ("THIN",       8, "CONTINUOUS", 25),   # тонкая сплошная
    ("CENTER",     4, "CENTER",     18),   # осевые и центровые
    ("HIDDEN",     1, "DASHED2",    18),   # невидимый контур
    ("DIMENSIONS", 3, "CONTINUOUS", 18),   # размеры и выноски
    ("TEXT",       2, "CONTINUOUS", 25),   # надписи
    ("TABLE",      7, "CONTINUOUS", 25),   # разграфка таблиц
    ("HATCH",      8, "CONTINUOUS", 18),   # штриховка
    ("SKETCH",     7, "CONTINUOUS", 60),   # схематичные эскизы в ведомостях
]


def new_doc(text_h=5.0, ltscale=2.0):
    """Документ с полным набором слоёв и стилей.

    text_h - базовая высота размерного текста; от неё считаются засечки,
    стрелки и отступы, чтобы оформление оставалось соразмерным чертежу.
    """
    doc = ezdxf.new("R2013", setup=["linetypes"])
    doc.units = ezdxf.units.MM
    doc.header["$INSUNITS"] = 4          # миллиметры
    doc.header["$LUNITS"] = 2            # десятичные
    doc.header["$LUPREC"] = 2
    doc.header["$MEASUREMENT"] = 1       # метрическая
    doc.header["$LTSCALE"] = ltscale
    doc.header["$CELTSCALE"] = 1.0

    doc.styles.add(TEXT_STYLE, font="isocpeur.ttf")

    for name, color, ltype, lw in LAYERS:
        lay = doc.layers.add(name, color=color, linetype=ltype)
        lay.dxf.lineweight = lw

    _dimstyles(doc, text_h)
    return doc


def _dimstyles(doc, h):
    asz = h * 0.5
    gap = h * 0.25

    # --- линейные размеры: засечки по ГОСТ 2.307 ---
    ds = doc.dimstyles.add("GOST_2307")
    for k, v in dict(
        dimtxsty=TEXT_STYLE, dimtxt=h, dimasz=asz, dimblk="ARCHTICK",
        dimtad=1, dimgap=gap, dimexe=h * 0.5, dimexo=h * 0.3,
        dimdec=0, dimlunit=2, dimzin=8, dimscale=1.0, dimlfac=1.0,
        dimtih=0, dimtoh=0,
    ).items():
        setattr(ds.dxf, k, v)
    ds.set_arrows(blk="ARCHTICK")

    # --- радиусы/диаметры: стрелка, текст на полке ---
    # ВАЖНО: без dimtmove=1 ezdxf не рисует выноску к вынесенному тексту.
    dr = doc.dimstyles.add("GOST_R")
    for k, v in dict(
        dimtxsty=TEXT_STYLE, dimtxt=h, dimasz=h * 0.6, dimblk="", dimldrblk="",
        dimtad=1, dimgap=gap, dimdec=0, dimzin=8, dimscale=1.0,
        dimtofl=0, dimtoh=1, dimtmove=1, dimupt=1, dimtix=0, dimcen=0.0,
    ).items():
        setattr(dr.dxf, k, v)

    # --- выноски-полки ---
    dl = doc.dimstyles.add("GOST_LEADER")
    for k, v in dict(
        dimtxsty=TEXT_STYLE, dimtxt=h, dimasz=h * 0.6,
        dimldrblk="", dimscale=1.0, dimgap=gap,
    ).items():
        setattr(dl.dxf, k, v)
