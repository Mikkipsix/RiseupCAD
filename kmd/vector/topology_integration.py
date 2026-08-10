# -*- coding: utf-8 -*-
"""Attach dimension topology diagnostics to pipeline results."""
from .dimension_topology import build_dimension_topology


def install(pipeline_module):
    if getattr(pipeline_module, "_dimension_topology_installed", False):
        return
    original = pipeline_module.vectorize

    def vectorize(*args, **kwargs):
        result = original(*args, **kwargs)
        result["dimension_topology"] = build_dimension_topology(
            result.get("used_dims", ()),
            result.get("segments", ()),
            result.get("scale", 1.0),
        )
        return result

    pipeline_module.vectorize = vectorize
    pipeline_module._dimension_topology_installed = True
