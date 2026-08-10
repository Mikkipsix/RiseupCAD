# -*- coding: utf-8 -*-
"""
Числа на чертеже, масштаб и регуляризация координат.

Главная идея модуля: распознанные числа - это не подписи, а ограничения.
Если на чертеже стоит 150, то расстояние между соответствующими выносными
линиями обязано быть ровно 150, а не 149.3, как намерил Хаф. Поэтому
координаты линий группируются в кластеры, а кластеры решаются методом
наименьших квадратов при жёстких ограничениях от размеров.
"""
import math
import os
from dataclasses import dataclass, field

import cv2
import numpy as np

def _probe_ocr():
    """Модуля pytesseract мало: нужен ещё и сам движок tesseract.

    Модуль ставится через pip и импортируется всегда, а движок - отдельная
    программа. Без неё первый же вызов падает, поэтому проверяется именно
    наличие исполняемого файла.
    """
    try:
        import pytesseract
    except Exception:
        return False, None
    import shutil
    exe = getattr(pytesseract.pytesseract, "tesseract_cmd", "tesseract")
    if shutil.which(exe) is None and not os.path.isfile(exe):
        # типовые места установки на Windows
        for c in (r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                  r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"):
            if os.path.isfile(c):
                pytesseract.pytesseract.tesseract_cmd = c
                return True, pytesseract
        return False, None
    return True, pytesseract


HAS_OCR, pytesseract = _probe_ocr()

NUM_CFG = "--psm 11 -c tessedit_char_whitelist=0123456789"
MIN_VALUE = 10
MIN_CONF = 35.0
OCR_SCALES = (2, 3, 4)
PAD = 20


@dataclass
class Num:
    value: int
    x: float
    y: float
    w: float
    h: float
    conf: float
    vertical: bool


@dataclass
class Dim:
    """Размер: значение и две выносные линии, между которыми он стоит."""
    value: int
    vertical: bool          # True - размер по вертикали
    a: float                # координата первой выносной, px
    b: float                # координата второй выносной, px
    line: float             # координата размерной линии, px
    num: Num = None
    ia: int = -1            # индексы кластеров, заполняются при снапе
    ib: int = -1
    meta: dict = field(default_factory=dict)


# =====================================================================
#  OCR
# =====================================================================
def ocr_scales(bw, target=44.0):
    """Подбирает увеличение под реальную высоту шрифта на листе.

    Tesseract уверенно читает знаки высотой 30-50 px. Фиксированное
    увеличение поэтому работает через раз: на плотной схеме цифры мелкие,
    на деталировке крупные. Высота оценивается по компактным связным
    компонентам - это и есть знаки.
    """
    ker_h = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 1))
    ker_v = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 25))
    lines = cv2.max(cv2.morphologyEx(bw, cv2.MORPH_OPEN, ker_h),
                    cv2.morphologyEx(bw, cv2.MORPH_OPEN, ker_v))
    txt = cv2.subtract(bw, cv2.dilate(lines, np.ones((3, 3), np.uint8)))
    n, _, st, _ = cv2.connectedComponentsWithStats(txt, 8)
    hs = [st[i, 3] for i in range(1, n)
          if 4 <= st[i, 3] <= 60 and 2 <= st[i, 2] <= 60 and st[i, 4] >= 12]
    if not hs:
        return (2, 3)
    h = float(np.median(hs))
    k = int(round(target / max(h, 1.0)))
    k = max(2, min(6, k))
    return tuple(sorted({max(2, k - 1), k, min(6, k + 1)}))


def _prep(bw, k):
    img = cv2.resize(255 - bw, None, fx=k, fy=k,
                     interpolation=cv2.INTER_CUBIC)
    return cv2.copyMakeBorder(img, PAD, PAD, PAD, PAD, cv2.BORDER_CONSTANT,
                              value=255)


def _boxes(img):
    try:
        d = pytesseract.image_to_data(img, config=NUM_CFG,
                                      output_type=pytesseract.Output.DICT)
    except Exception:
        return []                    # движок пропал на ходу - не падаем
    out = []
    for i in range(len(d["text"])):
        t = "".join(ch for ch in d["text"][i] if ch.isdigit())
        try:
            conf = float(d["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        if t and conf >= MIN_CONF and len(t) <= 5:
            out.append((int(t), d["left"][i], d["top"][i],
                        d["width"][i], d["height"][i], conf))
    return out


def ocr_numbers(bw, min_h=7, max_h=70, scales=None):
    """Числа. Второй проход по копии, повёрнутой ПО часовой стрелке:
    вертикальные размерные надписи по ГОСТ 2.307 читаются снизу вверх."""
    if not HAS_OCR:
        return []
    found = []
    # увеличения подбираются под высоту шрифта на этом листе
    for k in (scales or ocr_scales(bw)):
        img = _prep(bw, k)
        H = img.shape[0]
        for v, x, y, w, h, c in _boxes(img):
            found.append(Num(v, (x + w / 2.0 - PAD) / k,
                             (y + h / 2.0 - PAD) / k,
                             w / k, h / k, c, False))
        for v, x, y, w, h, c in _boxes(cv2.rotate(img,
                                                  cv2.ROTATE_90_CLOCKWISE)):
            rx, ry = x + w / 2.0, y + h / 2.0
            found.append(Num(v, (ry - PAD) / k, (H - 1 - rx - PAD) / k,
                             h / k, w / k, c, True))
    hh, ww = bw.shape
    out = []
    for f in sorted(found, key=lambda n: -n.conf):
        if f.value < MIN_VALUE or not (0 <= f.x < ww and 0 <= f.y < hh):
            continue
        if not (min_h <= max(f.w, f.h) <= max_h * 3):
            continue
        if any(math.hypot(f.x - g.x, f.y - g.y) < 12 for g in out):
            continue
        out.append(f)
    return out


# =====================================================================
#  Привязка чисел к выносным линиям
# =====================================================================
def build_dims(numbers, segs, reach=9.0):
    """Размер = расстояние между двумя выносными, между которыми стоит число.

    Длина отрезка для этого не годится: засечки вылезают за размерную
    линию, а соседние размеры в цепи коллинеарны и склеиваются в один.

    Из нескольких пар выносных выбирается та, относительно которой число
    стоит симметрично: по ГОСТ 2.307 размерное число ставится посередине
    своей размерной линии. Без этого правила размер 150 цепляется к
    ближайшей осевой отверстия вместо дальней кромки детали.
    """
    out = []
    for nb in numbers:
        want = "h" if nb.vertical else "v"     # выносные перпендикулярны
        cur = nb.x if want == "v" else nb.y
        line = nb.x if nb.vertical else nb.y
        # число стоит сбоку от своей размерной линии, поэтому допуск
        # «дотягивания» выносной берётся по размеру самого числа
        reach_n = max(reach, 1.6 * (nb.w if nb.vertical else nb.h))
        cands = []
        for s in segs:
            if s.kind != want:
                continue
            if want == "v":
                pos, a0, a1 = s.x1, min(s.y1, s.y2), max(s.y1, s.y2)
            else:
                pos, a0, a1 = s.y1, min(s.x1, s.x2), max(s.x1, s.x2)
            if a1 - a0 < 6:
                continue
            # выносная обязана доходить до уровня размерной линии
            if not (a0 - reach_n <= line <= a1 + reach_n):
                continue
            cands.append(pos)
        cands = sorted(set(round(c, 1) for c in cands))
        if len(cands) < 2:
            continue

        best = None
        for i in range(len(cands)):
            for j in range(i + 1, len(cands)):
                p, q = cands[i], cands[j]
                span = q - p
                if span < 8:
                    continue
                if p - 2 <= cur <= q + 2:
                    err = abs((cur - p) - (q - cur)) / span
                    if err > 0.40:
                        continue
                else:
                    err = 0.5 + min(abs(cur - p), abs(cur - q)) / span
                key = (round(err, 3), span)
                if best is None or key < best[0]:
                    best = (key, p, q)
        if best is None:
            continue
        _, a, b = best
        out.append(Dim(nb.value, nb.vertical, a, b, line, nb))
    return out


def calibrate(dims, rel_tol=0.05, allow_single=True):
    """Масштаб мм/px по самому населённому кластеру отношений.

    Если размер на листе распознан всего один, масштаб берётся по нему,
    но помечается как непроверенный: подтвердить его нечем.
    """
    if not dims:
        return None
    if len(dims) == 1:
        if not allow_single:
            return None
        d = dims[0]
        k = d.value / (d.b - d.a)
        return {"scale": k, "n": 1, "rms": 0.0, "single": True,
                "used": {id(d)}, "rejected": [],
                "matches": [{"value": d.value, "px": round(d.b - d.a, 1),
                             "mm": float(d.value), "resid": 0.0}]}
    ks = [(d, d.value / (d.b - d.a)) for d in dims]
    best = None
    for _, k0 in ks:
        inl = [(d, k) for d, k in ks if abs(k - k0) <= k0 * rel_tol]
        # вес по значениям, а не по длине: настоящие размеры - крупные
        # числа, а номера позиций мелкие и случайно образуют свой кластер
        score = (len(inl), sum(d.value for d, _ in inl))
        if best is None or score > best[0]:
            best = (score, inl)
    inl = best[1]
    if len(inl) < 2:
        return None
    num = sum(d.value * (d.b - d.a) for d, _ in inl)
    den = sum((d.b - d.a) ** 2 for d, _ in inl)
    k = num / den
    matches = [{"value": d.value, "px": round(d.b - d.a, 1),
                "mm": round((d.b - d.a) * k, 1),
                "resid": round((d.b - d.a) * k - d.value, 1)} for d, _ in inl]
    matches.sort(key=lambda m: -m["value"])
    rms = math.sqrt(sum(m["resid"] ** 2 for m in matches) / len(matches))
    used = {id(d) for d, _ in inl}
    return {"scale": k, "matches": matches, "rms": round(rms, 2),
            "n": len(matches), "used": used,
            "rejected": sorted({d.value for d in dims if id(d) not in used})}


# =====================================================================
#  Кластеризация координат и решение с ограничениями
# =====================================================================
def cluster(values, tol=4.0):
    """Группировка близких координат. Возвращает центры и индексы."""
    if not values:
        return [], {}
    order = sorted(range(len(values)), key=lambda i: values[i])
    centers, idx, cur = [], {}, [order[0]]
    start = values[order[0]]
    for i in order[1:]:
        # ширина кластера ограничена от его начала: иначе цепочка близких
        # значений склеивает в одно то, что на чертеже разные линии
        if values[i] - start <= tol:
            cur.append(i)
        else:
            centers.append(float(np.mean([values[j] for j in cur])))
            for j in cur:
                idx[j] = len(centers) - 1
            cur = [i]
            start = values[i]
    centers.append(float(np.mean([values[j] for j in cur])))
    for j in cur:
        idx[j] = len(centers) - 1
    return centers, idx


def nearest(centers, v, tol):
    if not centers:
        return -1
    i = int(np.argmin([abs(c - v) for c in centers]))
    return i if abs(centers[i] - v) <= tol else -1


def solve_axis(centers_px, constraints, scale, weight=40.0):
    """Положения кластеров в мм при ограничениях от размеров.

    constraints - список (i, j, value): расстояние между кластерами i и j
    обязано равняться value. Решается МНК: измеренные положения тянут к
    себе с весом 1, ограничения - с весом weight.
    """
    n = len(centers_px)
    if n == 0:
        return [], []
    rows, rhs = [], []
    for i in range(n):
        r = np.zeros(n)
        r[i] = 1.0
        rows.append(r)
        rhs.append(centers_px[i] * scale)
    for i, j, v in constraints:
        r = np.zeros(n)
        r[j] = weight
        r[i] = -weight
        rows.append(r)
        rhs.append(weight * v)
    A = np.array(rows)
    b = np.array(rhs)
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    resid = [(i, j, v, round(float(sol[j] - sol[i]) - v, 3))
             for i, j, v in constraints]
    return [float(x) for x in sol], resid


def refine_dims(numbers, segs, scale, rel_tol=0.04, reach=9.0):
    """Второй проход привязки, когда масштаб уже известен.

    На первом проходе пара выносных выбирается по симметрии - этого хватает,
    чтобы подобрать масштаб, но часть размеров цепляется не туда. Зная
    масштаб, можно требовать прямого совпадения: расстояние между
    выносными, умноженное на масштаб, обязано дать написанное число.
    """
    out = []
    for nb in numbers:
        want = "h" if nb.vertical else "v"
        cur = nb.x if want == "v" else nb.y
        line = nb.x if nb.vertical else nb.y
        reach_n = max(reach, 1.6 * (nb.w if nb.vertical else nb.h))
        cands = []
        for s in segs:
            if s.kind != want:
                continue
            if want == "v":
                pos, a0, a1 = s.x1, min(s.y1, s.y2), max(s.y1, s.y2)
            else:
                pos, a0, a1 = s.y1, min(s.x1, s.x2), max(s.x1, s.x2)
            if a1 - a0 < 6 or not (a0 - reach_n <= line <= a1 + reach_n):
                continue
            cands.append(round(pos, 1))
        cands = sorted(set(cands))
        target = nb.value / scale                     # ожидаемое расстояние, px
        best = None
        for i in range(len(cands)):
            for j in range(i + 1, len(cands)):
                p, q = cands[i], cands[j]
                span = q - p
                if span < 8:
                    continue
                err = abs(span - target) / target
                if err > rel_tol:
                    continue
                # при равной точности предпочесть пару, охватывающую число
                inside = 0 if p - 2 <= cur <= q + 2 else 1
                key = (inside, round(err, 4))
                if best is None or key < best[0]:
                    best = (key, p, q)
        if best is None:
            continue
        _, a, b = best
        out.append(Dim(nb.value, nb.vertical, a, b, line, nb))
    return out
