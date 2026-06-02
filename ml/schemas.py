"""Pydantic v2 models for ML forecasting."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class FeatureVector(BaseModel):
    bin_id: str
    at_time: datetime
    # Temporal fill state
    fill_pct_current: float = Field(ge=0.0, le=100.0)
    fill_rate_1h: float = 0.0    # %/hr over last 2 readings
    fill_rate_3h: float = 0.0    # %/hr over last 6 readings
    fill_rate_6h: float = 0.0    # %/hr over last 12 readings
    fill_rate_24h: float = 0.0   # %/hr over last 48 readings
    rolling_std_6h: float = 0.0  # std of fill_pct over last 12 readings
    time_since_last_empty: float = 168.0   # hours; default 1 week if never emptied
    fill_at_last_empty: float = 0.0
    # Time context
    hour_of_day: int = Field(ge=0, le=23)
    day_of_week: int = Field(ge=0, le=6)   # 0=Mon, 6=Sun
    is_weekend: bool = False
    is_peak_morning: bool = False    # 07:00–09:00
    is_peak_evening: bool = False    # 17:00–20:00
    days_until_next_holiday: int = 30
    # Bin context (one-hot zone)
    zone_type_residential: int = 0
    zone_type_commercial: int = 0
    zone_type_park: int = 0
    zone_type_transit_hub: int = 0
    capacity_liters: float = 120.0
    priority_level: int = Field(default=1, ge=1, le=3)
    sector_avg_fill: float = 0.0
    # Anomaly signals
    spike_count_24h: int = 0
    fault_count_24h: int = 0
    is_volatile: bool = False   # rolling_std_6h > 8.0
    # Exogenous features (Phase 5 — populated by ExogenousInjector)
    weather_fill_multiplier: float = 1.0
    outdoor_activity_score: float = 0.5
    is_raining: bool = False
    forecast_rain_6h: bool = False
    zone_congestion_ratio: float = 0.7
    estimated_truck_delay_min: float = 0.0
    calendar_fill_multiplier: float = 1.0
    days_until_next_high_impact: int = 30
    is_holiday_today: bool = False


class PredictionResult(BaseModel):
    bin_id: str
    predicted_at: datetime
    hours_until_critical: float = Field(ge=0.0, le=24.0)
    fill_pct_current: float
    model_used: str   # "ensemble" | "prophet" | "gbm" | "extrapolation"
    confidence: float = Field(ge=0.0, le=1.0)
    prophet_hours: Optional[float] = None
    gbm_hours: Optional[float] = None


class TrainingResult(BaseModel):
    bin_id: str
    zone_id: str
    trained_at: datetime
    prophet_trained: bool = False
    gbm_trained: bool = False
    n_samples: int = 0
    error: Optional[str] = None


class ModelStatus(BaseModel):
    bin_id: str
    has_prophet: bool = False
    has_gbm: bool = False
    last_trained: Optional[datetime] = None
