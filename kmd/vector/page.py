# -*- coding: utf-8 -*-
"""Загрузка страницы (растр или PDF), бинаризация, устранение перекоса."""
import math
import os

import cv2
import numpy as np


def page_count(path):
    if os.path.splitext(path)[1].lower() != ".pdf":
        return 1
    import pypdfium2 as pdfium
    return len(pdfium.PdfDocument(path))


def load_page(path, dpi=200, page=0):
    """Изображение в градациях серого (uint8)."""
    if os.path.splitext(path)[1].lower() == ".pdf":
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(path)
        pil = pdf[page].render(scale=dpi / 72.0).to_pil().convert("L")
        return np.array(pil)
    from PIL import Image
    return np.array(Image.open(path).convert("L"))


def hough_rows(arr, width):
    """Строки результата Хафа независимо от версии OpenCV.

    В OpenCV 4.x HoughLinesP возвращает массив (N, 1, 4), а в 5.x - (N, 4);
    у HoughCircles аналогично (1, N, 3) и (N, 3). Без приведения к общему
    виду распаковка падает с «cannot unpack non-iterable numpy.int32».
    """
    if arr is None:
        return []
    a = np.asarray(arr)
    if a.size == 0:
        return []
    return a.reshape(-1, width)


def stroke_width(bw, samples=200):
    """Медианная толщина штриха по горизонтальным пробегам туши."""
    runs = []
    h = bw.shape[0]
    step = max(1, h // samples)
    for y in range(0, h, step):
        n = 0
        for v in bw[y]:
            if v:
                n += 1
            elif n:
                if 1 <= n <= 15:
                    runs.append(n)
                n = 0
        if 1 <= n <= 15:
            runs.append(n)
    return float(np.median(runs)) if runs else 0.0


def upscale_factor(bw, want=3.0, max_k=3):
    """Во сколько раз увеличить лист.

    Решает не размер листа, а толщина штриха. На скане от руки штрих
    занимает 3-4 пикселя, и увеличивать нечего. На плотной схеме,
    выведенной из CAD, линия занимает один-два пикселя: Хаф теряет
    отрезки, толщина не измеряется, OCR не читает цифры. Увеличение
    нужно только во втором случае.
    """
    w = stroke_width(bw)
    if w <= 0:
        return 1
    return max(1, min(max_k, int(round(want / w))))


def upscale(gray, k):
    if k <= 1:
        return gray
    return cv2.resize(gray, None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC)


def binarize(gray):
    """Тушь = 255. Фон выравнивается делением на размытую копию,
    поэтому серая бумага и неравномерная засветка скана не мешают."""
    bg = cv2.medianBlur(gray, 31)
    norm = cv2.divide(gray, bg, scale=255)
    bw = cv2.adaptiveThreshold(norm, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                               cv2.THRESH_BINARY_INV, 31, 12)
    return cv2.morphologyEx(bw, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))


def deskew(bw, gray, max_angle=5.0):
    """Поворот по преобладающему направлению длинных отрезков."""
    lines = cv2.HoughLinesP(bw, 1, np.pi / 720, threshold=120,
                            minLineLength=max(bw.shape) // 8, maxLineGap=6)
    if lines is None:
        return bw, gray, 0.0
    angs = []
    for x1, y1, x2, y2 in hough_rows(lines, 4):
        a = math.degrees(math.atan2(y2 - y1, x2 - x1)) % 90.0
        if a > 45:
            a -= 90.0
        if abs(a) <= max_angle:
            angs.append(a)
    if not angs:
        return bw, gray, 0.0
    ang = float(np.median(angs))
    if abs(ang) < 0.05:
        return bw, gray, 0.0
    h, w = bw.shape
    M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
    return (cv2.warpAffine(bw, M, (w, h), flags=cv2.INTER_NEAREST),
            cv2.warpAffine(gray, M, (w, h), flags=cv2.INTER_LINEAR,
                           borderValue=255),
            ang)
