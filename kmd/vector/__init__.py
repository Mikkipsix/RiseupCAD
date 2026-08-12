# -*- coding: utf-8 -*-
"""Распознавание растровых чертежей в DXF."""
from . import assemble, detect, page, pipeline, solve  # noqa: F401,E501
from .calibration_policy import install as _install_calibration_policy
from .dimension_selection_v9 import install as _install_dimension_selection_v9
from .dimension_selection_v10 import install as _install_dimension_selection_v10
from .topology_integration import install as _install_topology
from .pipeline import overlay_png, summary, to_dxf, vectorize  # noqa: F401

_install_calibration_policy(solve)
_install_dimension_selection_v9(solve)
_install_dimension_selection_v10(solve)
_install_topology(pipeline)
vectorize = pipeline.vectorize

__all__ = ["vectorize", "to_dxf", "overlay_png", "summary"]
