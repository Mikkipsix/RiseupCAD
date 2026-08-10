# -*- coding: utf-8 -*-
"""Конвейер: страница -> примитивы -> модель -> DXF, плюс отчёт и контроль."""
import math

import cv2
import numpy as np

from . import assemble, detect, page, solve

HAS_OCR = solve.HAS_OCR
load_page = page.load_page
page_count = page.page_count


def _calibration_dims(good, cal):
    """Return only dimensions that survived the final calibration cluster."""
    if not good or not cal:
        return []
    used = cal.get("used", set())
    return [d for d in good if id(d) in used]


def vectorize(path, dpi=200, page_no=0, min_len=25, do_ocr=True,
              scale_override=None, **kw):
    page_no = int(kw.pop("page", page_no) or 0)
    gray = page.load_page(path, dpi=dpi, page=page_no)
    up = page.upscale_factor(page.binarize(gray))
    if up > 1:
        gray = page.upscale(gray, up)
        min_len = max(8, int(min_len * up))
    bw = page.binarize(gray)
    bw, gray, ang = page.deskew(bw, gray)

    segs = detect.detect_segments(bw, min_len=min_len)
    boxes = detect.text_boxes(bw) if do_ocr and solve.HAS_OCR else []
    H0, W0 = bw.shape
    boxes = [b for b in boxes if b[3] <= 0.10 * H0 and b[2] <= 0.35 * W0]
    segs = [s for s in segs if not _in_text(s, boxes)]
    thr = detect.split_by_weight(segs)
    circles = detect.circles_at_crosses(bw, segs)
    arcs = detect.detect_arcs_all(bw, boxes=boxes)
    ocr_k = None if up > 1 else (2,)
    numbers = (solve.ocr_numbers(bw, scales=ocr_k)
               if (do_ocr and solve.HAS_OCR) else [])
    dims = solve.build_dims(numbers, segs)
    cal = solve.calibrate(dims)

    if scale_override:
        scale = float(scale_override)
        source = "задан вручную"
    elif cal:
        scale = cal["scale"]
        source = ("подобран по единственному размеру, проверить нечем"
                  if cal.get("single") else
                  f'подобран по {cal["n"]} размерам, СКО {cal["rms"]} мм')
    else:
        scale = 1.0
        source = "не определён, координаты в пикселях"

    if scale != 1.0:
        good = solve.refine_dims(numbers, segs, scale)
        if not good and cal:
            good = [d for d in dims if id(d) in cal["used"]]
        if cal and not cal.get("single"):
            k2 = solve.calibrate(good) if len(good) >= 2 else None
            if k2 and k2["rms"] <= cal["rms"] + 0.5 and not scale_override:
                scale = k2["scale"]
                cal = k2
                source = (f'подобран по {k2["n"]} размерам, '
                          f'СКО {k2["rms"]} мм')
                good = solve.refine_dims(numbers, segs, scale)
    else:
        good = []

    # good = all successfully refined dimensions used by the CAD model.
    # used_dims = only the dimensions that actually support final calibration.
    # This distinction prevents false OCR values such as 3000 from becoming
    # calibration constraints while keeping valid small dimensions in the model.
    used_dims = _calibration_dims(good, cal)

    model = assemble.build_model(segs, circles, good, numbers, scale,
                                 gray.shape[0], arcs=arcs)
    opts = []
    seen = set()
    for d in sorted(dims, key=lambda d: -d.value):
        k = (d.value, round(d.b - d.a, 1))
        if k in seen:
            continue
        seen.add(k)
        opts.append({"value": d.value, "px": round(d.b - d.a, 1),
                     "scale": round(d.value / (d.b - d.a), 5)})

    lens, seen_len = [], set()
    for x in sorted(segs, key=lambda x: -x.length):
        if x.role == "leader" or x.length < 20:
            continue
        k = round(x.length / 3.0)
        if k in seen_len:
            continue
        seen_len.add(k)
        lens.append({"px": round(x.length, 1),
                     "kind": "гориз." if x.kind == "h" else "вертик.",
                     "role": x.role})
        if len(lens) >= 12:
            break

    return {"gray": gray, "bw": bw, "segments": segs, "circles": circles,
            "arcs": arcs, "line_options": lens, "has_ocr": solve.HAS_OCR,
            "upscale": up,
            "numbers": numbers, "dims": dims, "used_dims": used_dims,
            "all_dims": good,
            "calib": cal, "options": opts, "scale": scale,
            "scale_source": source, "deskew": round(ang, 2),
            "weight_threshold": round(thr, 2), "model": model,
            "size": (gray.shape[1], gray.shape[0])}


def _in_text(s, boxes, grow=2.0):
    for bx, by, bw_, bh in boxes:
        if bw_ * bh < 25:
            continue
        if (bx - grow <= min(s.x1, s.x2) and max(s.x1, s.x2) <= bx + bw_ + grow
                and by - grow <= min(s.y1, s.y2)
                and max(s.y1, s.y2) <= by + bh + grow):
            return True
    return False


def to_dxf(res, path, put_text=True, **kw):
    model = res["model"]
    if not put_text:
        model.texts = []
    return assemble.to_dxf(model, path)


# =====================================================================
#  Контроль
# =====================================================================
def overlay_png(res, max_side=1500):
    img = cv2.cvtColor(res["gray"], cv2.COLOR_GRAY2BGR)
    img = (img * 0.30 + 170).astype(np.uint8)
    col = {"contour": (230, 80, 30), "thin": (150, 150, 150),
           "center": (200, 60, 200), "leader": (120, 190, 90)}
    for s in res["segments"]:
        c = col.get(s.role, (120, 120, 120))
        w = 3 if s.role == "contour" else 1
        cv2.line(img, (int(s.x1), int(s.y1)), (int(s.x2), int(s.y2)), c, w)
    for a in res.get("arcs", ()):
        cv2.ellipse(img, (int(a.cx), int(a.cy)), (int(a.r), int(a.r)), 0,
                    math.degrees(a.a0),
                    math.degrees(a.a0) + math.degrees(a.sweep()),
                    (40, 120, 240), 2)
    for c in res["circles"]:
        cv2.circle(img, (int(c.cx), int(c.cy)), int(round(c.r)), (30, 170, 30), 2)
        cv2.drawMarker(img, (int(c.cx), int(c.cy)), (30, 170, 30),
                       cv2.MARKER_CROSS, 10, 1)
    used = {id(d.num) for d in res["used_dims"] if d.num is not None}
    for nb in res["numbers"]:
        c = (0, 140, 255) if id(nb) in used else (170, 60, 200)
        x, y = int(nb.x - nb.w / 2), int(nb.y - nb.h / 2)
        cv2.rectangle(img, (x - 2, y - 2), (x + int(nb.w) + 2,
                                            y + int(nb.h) + 2), c, 2)
        cv2.putText(img, str(nb.value), (x, y - 5), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, c, 1, cv2.LINE_AA)
    h, w = img.shape[:2]
    if max(h, w) > max_side:
        f = max_side / max(h, w)
        img = cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", img)
    return buf.tobytes() if ok else b""


def summary(res):
    m = res["model"]
    rep = m.notes[0] if m.notes else {}
    roles = {}
    for s in res["segments"]:
        roles[s.role] = roles.get(s.role, 0) + 1
    out = [
        f'лист: {res["size"][0]}x{res["size"][1]} px'
        + (f' (увеличен x{res["upscale"]})' if res.get("upscale", 1) > 1 else "")
        + f', перекос {res["deskew"]}°',
        f'линии: контур {roles.get("contour", 0)}, тонкие '
        f'{roles.get("thin", 0)}, осевые {roles.get("center", 0)}, '
        f'наклонные {roles.get("leader", 0)}   '
        f'(порог толщины {res["weight_threshold"]} px)',
        f'отверстий: {len(res["circles"])}   дуг: {len(res["arcs"])}   '
        f'чисел: {len(res["numbers"])}',
        f'масштаб: {res["scale"]:.4f} мм/px ({res["scale_source"]})',
        "",
        f'модель: замкнутых контуров {len(m.polys)}, отдельных линий '
        f'{len(m.lines)}, окружностей {len(m.circles)}, дуг {len(m.arcs)}, '
        f'размеров DIMENSION {len(m.dims)}',
    ]
    if not res.get("has_ocr", True):
        out += ["",
                "Движок tesseract не установлен, числа с чертежа не читаются.",
                "Геометрия распознана, но масштаб задать нечем: укажите его",
                "вручную или откалибруйте по линии с известной длиной."]
    c = res["calib"]
    if c:
        out += ["", "сверка размеров, по которым подобран масштаб:",
                f'{"размер":>8} {"px":>8} {"расчёт":>8} {"невязка":>9}']
        for mm in c["matches"]:
            out.append(f'{mm["value"]:>8} {mm["px"]:>8} {mm["mm"]:>8} '
                       f'{mm["resid"]:>+9}')
        if c["rejected"]:
            out.append(f'не вошли в кластер: {c["rejected"]}')
    elif res["numbers"]:
        out += ["", "масштаб подобрать не удалось: числа не легли в общий "
                "кластер. Задайте масштаб вручную."]
    if rep.get("constraints"):
        bad = [r for r in rep["resid"] if abs(r[3]) > 0.05]
        out += ["", f'притянуто координат: {rep["clusters_x"]} по X, '
                f'{rep["clusters_y"]} по Y при {rep["constraints"]} '
                f'ограничениях от размеров',
                f'ограничений с невязкой > 0.05 мм: {len(bad)}']
    if rep.get("unmatched"):
        out.append(f'размеры без привязки к линиям: {rep["unmatched"]}')
    return "\n".join(out)
