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
    for x1, y1, x2, y2 in lines[:, 0]:
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
