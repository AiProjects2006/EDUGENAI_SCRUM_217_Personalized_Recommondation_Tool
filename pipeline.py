"""End-to-End 5-Stage Personalized Recommendation Tool Pipeline Orchestrator."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Set

from learning_profile_analysis import LearningProfileAnalyzer
from models import (
    ClientContextPayload,
    CollectedStudentData,
    RecommendationToolOutput,
)
from recommendation_generation import RecommendationGenerator
from recommendation_ranking import RecommendationRanker
from student_data_collection import StudentDataCollector
from student_learning_profile import StudentLearningProfileBuilder


class RecommendationPipeline:
    """Executes all 5 stages of the Personalized Recommendation Tool."""

    def __init__(
        self,
        collector: Optional[StudentDataCollector] = None,
        profile_builder: Optional[StudentLearningProfileBuilder] = None,
        analyzer: Optional[LearningProfileAnalyzer] = None,
        generator: Optional[RecommendationGenerator] = None,
        ranker: Optional[RecommendationRanker] = None,
    ) -> None:
        self.collector = collector or StudentDataCollector()
        self.profile_builder = profile_builder or StudentLearningProfileBuilder()
        self.analyzer = analyzer or LearningProfileAnalyzer()
        self.generator = generator or RecommendationGenerator()
        self.ranker = ranker or RecommendationRanker()

    def run_from_collected(
        self,
        collected: CollectedStudentData,
        dismissed_ids: Optional[Set[str]] = None,
    ) -> RecommendationToolOutput:
        """Run Stages 2-5 from an already-collected Stage 1 student data bundle."""
        profile = self.profile_builder.build(collected)
        analysis = self.analyzer.analyze(profile)
        candidates, mascot_tip = self.generator.generate(collected, profile, analysis)
        ranked = self.ranker.rank(
            candidates=candidates,
            profile=profile,
            analysis=analysis,
            dismissed_ids=dismissed_ids,
        )

        recommended_courses = [r for r in ranked if r.itemType == "COURSE"][:6]
        recommended_activities = [
            r for r in ranked if r.itemType in {"ACTIVITY", "AI_PRACTICE"}
        ][:8]
        study_tips = [r for r in ranked if r.itemType == "STUDY_TIP"][:4]

        return RecommendationToolOutput(
            userId=collected.userId,
            generatedAt=datetime.now(timezone.utc).isoformat(),
            mascotTip=mascot_tip,
            profile=profile,
            analysis=analysis,
            recommendations=ranked,
            recommendedCourses=recommended_courses,
            recommendedActivities=recommended_activities,
            studyTips=study_tips,
            sourceHealth=collected.sourceHealth,
        )

    async def run(
        self,
        user_id: int,
        client_context: Optional[ClientContextPayload] = None,
        auth_header: Optional[str] = None,
        dismissed_ids: Optional[Set[str]] = None,
    ) -> RecommendationToolOutput:
        """Run Stages 1-5 end-to-end and return a structured RecommendationToolOutput."""
        collected = await self.collector.collect(
            user_id=user_id,
            client_context=client_context,
            auth_header=auth_header,
        )
        return self.run_from_collected(collected, dismissed_ids=dismissed_ids)
