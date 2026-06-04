"""Pydantic v2 models for geospatial registry."""
from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


class Zone(BaseModel):
    zone_id: str
    name: str
    zone_type: str
    priority_level: int = 1
    assigned_trucks: int = 2
    min_lat: Optional[float] = None
    max_lat: Optional[float] = None
    min_lng: Optional[float] = None
    max_lng: Optional[float] = None


class Sector(BaseModel):
    sector_id: str
    zone_id: str
    name: str
    bin_count: int = 0
    min_lat: Optional[float] = None
    max_lat: Optional[float] = None
    min_lng: Optional[float] = None
    max_lng: Optional[float] = None


class BinRegistryEntry(BaseModel):
    bin_id: str
    lat: float
    lng: float
    zone_type: str
    zone_id: Optional[str] = None
    sector_id: Optional[str] = None
    capacity_liters: int
    priority_level: int = 1
    is_active: bool = True
    road_access: str = "standard"
    distance_km: Optional[float] = None  # populated by nearest queries


class DumpYard(BaseModel):
    yard_id: str
    name: str
    lat: float
    lng: float
    capacity_tons: Optional[int] = None
    operating_hours: Optional[str] = None
    is_active: bool = True
    distance_km: Optional[float] = None  # populated by nearest query


# GeoJSON types for export endpoints

class GeoJSONPoint(BaseModel):
    type: str = "Point"
    coordinates: list[float]  # [lng, lat]


class GeoJSONPolygon(BaseModel):
    type: str = "Polygon"
    coordinates: list[list[list[float]]]  # [[[lng,lat], ...]]


class GeoJSONFeature(BaseModel):
    type: str = "Feature"
    geometry: dict[str, Any]
    properties: dict[str, Any]


class GeoJSONFeatureCollection(BaseModel):
    type: str = "FeatureCollection"
    features: list[GeoJSONFeature]
