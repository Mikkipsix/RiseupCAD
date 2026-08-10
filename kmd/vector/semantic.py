# -*- coding: utf-8 -*-
"""Semantic CAD model used as the boundary between recognition and DXF."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import json
from typing import Any

ALLOWED_TYPES = {"LINE","POLYLINE","CIRCLE","ARC","TEXT","DIMENSION","HATCH","POINT","BLOCK","TABLE","UNKNOWN"}

@dataclass
class CadObject:
    type: str
    layer: str = "GEOMETRY"
    confidence: float = 0.0
    source: dict[str, Any] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.type = self.type.upper()
        if self.type not in ALLOWED_TYPES:
            self.type = "UNKNOWN"
        self.confidence = max(0.0, min(1.0, float(self.confidence)))

    def validate(self):
        if self.type == "LINE" and not {"start", "end"} <= self.data.keys():
            raise ValueError("LINE requires start/end")
        if self.type == "CIRCLE" and not {"center", "radius"} <= self.data.keys():
            raise ValueError("CIRCLE requires center/radius")
        if self.type == "ARC" and not {"center", "radius"} <= self.data.keys():
            raise ValueError("ARC requires center/radius")
        if self.type == "POLYLINE" and len(self.data.get("points", [])) < 2:
            raise ValueError("POLYLINE requires at least 2 points")
        if self.type == "DIMENSION" and not {"value", "p1", "p2"} <= self.data.keys():
            raise ValueError("DIMENSION requires value/p1/p2")
        return True

    def to_dict(self):
        self.validate()
        return {"type": self.type, "layer": self.layer,
                "confidence": self.confidence, "source": self.source,
                "data": self.data}

@dataclass
class DrawingModel:
    units: str = "mm"
    scale: float | None = None
    width_px: int | None = None
    height_px: int | None = None
    objects: list[CadObject] = field(default_factory=list)
    layers: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add(self, obj: CadObject):
        obj.validate()
        self.objects.append(obj)
        if obj.layer not in self.layers:
            self.layers.append(obj.layer)
        return obj

    def by_type(self, kind: str):
        return [o for o in self.objects if o.type == kind.upper()]

    def confidence(self):
        return (sum(o.confidence for o in self.objects) / len(self.objects)) if self.objects else 0.0

    def to_dict(self):
        return {"schema_version": "0.1", "units": self.units, "scale": self.scale,
                "width_px": self.width_px, "height_px": self.height_px,
                "layers": self.layers, "metadata": self.metadata,
                "objects": [o.to_dict() for o in self.objects]}

    def save_json(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return path
