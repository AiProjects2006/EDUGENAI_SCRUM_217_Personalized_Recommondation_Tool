"""Tests for Personalized Recommendation Tool Foundation setup, config, and Pydantic schemas."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from personalized_recommendation_tool.config import Settings, settings
from personalized_recommendation_tool.models import (
    BadgeOpportunity,
    ClientContextPayload,
    CollectedStudentData,
    LearningProfileAnalysis,
    RecommendationCandidate,
    RecommendationToolOutput,
    StudentLearningProfile,
    SubjectLearningStat,
)


class SetupAndModelsTests(unittest.TestCase):
    def test_settings_defaults_match_microservices_architecture(self) -> None:
        cfg = Settings()
        self.assertEqual(cfg.tool_port, 8001)
        self.assertEqual(cfg.user_service_url, "http://localhost:8081")
        self.assertEqual(cfg.course_service_url, "http://localhost:8082")
        self.assertEqual(cfg.activity_service_url, "http://localhost:8083")
        self.assertEqual(cfg.enrollment_service_url, "http://localhost:8084")
        self.assertEqual(cfg.settings_service_url, "http://localhost:8084")
        self.assertEqual(cfg.progress_service_url, "http://localhost:8088")
        self.assertFalse(hasattr(settings, "mysql_database"))

    def test_collected_student_data_and_profile_defaults(self) -> None:
        ctx = ClientContextPayload(studentName="Nethmi", gradeLevel="Grade 4")
        collected = CollectedStudentData(userId=12, clientContext=ctx)
        self.assertEqual(collected.userId, 12)
        self.assertTrue(collected.collectedAt)

        stat = SubjectLearningStat(subject="Mathematics", masteryPercentage=45.0, averageScore=52.5)
        profile = StudentLearningProfile(userId=12, subjectStats={"Mathematics": stat})
        self.assertEqual(profile.gradeLevel, "Grade 4")
        self.assertEqual(profile.subjectStats["Mathematics"].trend, "NOT_STARTED")

    def test_recommendation_tool_output_schema(self) -> None:
        profile = StudentLearningProfile(userId=5)
        analysis = LearningProfileAnalysis(
            badgeOpportunities=[
                BadgeOpportunity(
                    badgeId="first_quest",
                    badgeName="First Quest",
                    icon="twemoji:star",
                    requirement="Pass 1 Activity Map exercise",
                    progressText="0/1",
                )
            ]
        )
        candidate = RecommendationCandidate(
            recommendationId="course-1",
            itemType="COURSE",
            actionType="ENROLL",
            title="Fractions Quest",
            description="Grade 4 Math",
            subject="Mathematics",
            priorityScore=88.5,
            rank=1,
        )
        output = RecommendationToolOutput(
            userId=5,
            generatedAt="2026-11-27T00:00:00Z",
            mascotTip="Start with Fractions Quest!",
            profile=profile,
            analysis=analysis,
            recommendations=[candidate],
            recommendedCourses=[candidate],
            recommendedActivities=[],
            studyTips=[],
            sourceHealth={"courseService": "ok"},
        )
        self.assertEqual(output.recommendations[0].rank, 1)
        self.assertFalse((ROOT / "ai_recommendation_service").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
