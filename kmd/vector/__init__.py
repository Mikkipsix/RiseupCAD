# -*- coding: utf-8 -*-
"""Распознавание растровых чертежей в DXF."""
from . import assemble, detect, page, pipeline, solve  # noqa: F401,E501
from .pipeline import overlay_png, summary, to_dxf, vectorize  # noqa: F401
from .topology_integration import install as _install_topology

_install_topology(pipeline)
vectorize = pipeline.vectorize

__all__ = ["vectorize", "to_dxf", "overlay_png", "summary"]
