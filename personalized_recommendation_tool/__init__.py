"""Personalized Recommendation Tool package."""

from personalized_recommendation_tool.config import Settings, settings
from personalized_recommendation_tool.student_data_collection import (
    StudentDataCollector,
    is_creator_published_activity,
)

__all__ = [
    "Settings",
    "settings",
    "StudentDataCollector",
    "is_creator_published_activity",
]
