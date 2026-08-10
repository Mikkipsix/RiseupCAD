# -*- coding: utf-8 -*-
"""Распознавание растровых чертежей в DXF."""
from . import assemble, detect, page, pipeline, solve  # noqa: F401,E501
from .calibration_policy import install as _install_calibration_policy
from .pipeline import overlay_png, summary, to_dxf, vectorize  # noqa: F401

_install_calibration_policy(solve)

__all__ = ["vectorize", "to_dxf", "overlay_png", "summary"]
