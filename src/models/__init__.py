"""Persisted wildfire models."""
from .capacity import CapacityAssumption
from .crossborder_notification import CrossborderNotification
from .event_notes import EventNote
from .exposure import ExposedAsset
from .fire import FireCluster, FireObservation, FirmsSyncStatus
from .fwi import FireWeatherIndex
from .historical_fire import HistoricalFirePerimeter
from .inventory import SuppressionResource
from .land_cover import LandCoverDataPoint
from .live import LiveUpdate
from .notification_center import NotificationSoundSetting, NotificationState
from .perf_budget import RecomputeLatencySample
from .pipeline import PipelineJobHistory
from .recommendation import RecommendationDecision
from .road_network import CrewBase, RoadClosure, RoadSegment
from .scenario import WhatIfHistory, WhatIfScenario
from .share_policy import CountrySharePolicy
from .spread_metrics import SpreadEvaluationMetric
from .spread_perf import SpreadPerformanceRun
from .spatial import (
    FireEvent,
    FireForecast,
    NaturalBarrier,
    SilentRegion,
    SimulationScenario,
    SpatialSource,
)
from .synthetic import ScenarioRun
from .topography import TopographyDataPoint
from .user_preferences import UserPreference
from .weather import WeatherDataPoint

__all__ = [
    "CapacityAssumption",
    "CrossborderNotification",
    "CrewBase",
    "EventNote",
    "ExposedAsset",
    "FireCluster",
    "FireEvent",
    "FireForecast",
    "FireObservation",
    "FireWeatherIndex",
    "FirmsSyncStatus",
    "HistoricalFirePerimeter",
    "LandCoverDataPoint",
    "LiveUpdate",
    "NaturalBarrier",
    "NotificationSoundSetting",
    "NotificationState",
    "PipelineJobHistory",
    "RecomputeLatencySample",
    "RecommendationDecision",
    "RoadClosure",
    "RoadSegment",
    "ScenarioRun",
    "SilentRegion",
    "SimulationScenario",
    "CountrySharePolicy",
    "SpatialSource",
    "WhatIfHistory",
    "WhatIfScenario",
    "SpreadEvaluationMetric",
    "SpreadPerformanceRun",
    "SuppressionResource",
    "TopographyDataPoint",
    "UserPreference",
    "WeatherDataPoint",
]
