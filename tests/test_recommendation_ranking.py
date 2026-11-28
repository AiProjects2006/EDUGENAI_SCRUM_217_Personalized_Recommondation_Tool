"""Tests for Stage 5: Recommendation Ranking and End-to-End 5-Stage Pipeline."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import unittest
import httpx

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from learning_profile_analysis import LearningProfileAnalyzer
from models import (
    BadgeOpportunity,
    ClientContextPayload,
    CollectedStudentData,
    LearningProfileAnalysis,
    RecommendationCandidate,
    RecommendationToolOutput,
    StudentLearningProfile,
    SubjectLearningStat,
)
from pipeline import RecommendationPipeline
from recommendation_generation import RecommendationGenerator
from recommendation_ranking import RecommendationRanker
from student_data_collection import StudentDataCollector
from student_learning_profile import StudentLearningProfileBuilder


def _mock_microservices_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if ":8081/api/users/42" in url:
            return httpx.Response(200, json={"id": 42, "firstName": "Nethmi", "lastName": "Perera"})
        if ":8084/api/v1/preferences/user/42" in url:
            return httpx.Response(
                200, json={"userId": 42, "learningStyle": "VISUAL", "difficultyLevel": "ADAPTIVE"}
            )
        if ":8084/api/v1/enrollments/user/42" in url:
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": [
                        {"enrollmentId": 10, "courseId": 101, "status": "ACTIVE", "studentGrade": "Grade 4"},
                        {"enrollmentId": 11, "courseId": 109, "status": "COMPLETED"},
                    ],
                },
            )
        if ":8082/api/v1/subjects" in url:
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": [
                        {"subjectId": 1, "name": "Mathematics"},
                        {"subjectId": 2, "name": "ICT"},
                        {"subjectId": 3, "name": "Environmental Studies"},
                    ],
                },
            )
        if ":8082/api/v1/courses" in url:
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": [
                        {
                            "courseId": 101,
                            "subjectId": 1,
                            "title": "Fractions & Decimals",
                            "gradeLevel": "Grade 4",
                            "level": "INTERMEDIATE",
                            "status": "PUBLISHED",
                        },
                        {
                            "courseId": 102,
                            "subjectId": 2,
                            "title": "Digital Tools",
                            "gradeLevel": "Grade 4",
                            "level": "BEGINNER",
                            "status": "PUBLISHED",
                        },
                        {
                            "courseId": 109,
                            "subjectId": 3,
                            "title": "Completed Nature Course",
                            "gradeLevel": "Grade 4",
                            "status": "PUBLISHED",
                        },
                    ],
                },
            )
        if ":8082/api/v1/modules" in url:
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": [
                        {"moduleId": 201, "courseId": 101, "title": "Pizza Fractions"},
                        {"moduleId": 202, "courseId": 102, "title": "Safe Browsing"},
                    ],
                },
            )
        if ":8083/api/v1/activities" in url:
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": [
                        {
                            "activityId": 301,
                            "moduleId": 201,
                            "displayOrder": 1,
                            "title": "Half & Quarter Quiz",
                            "activityType": "MCQ",
                            "difficulty": "MEDIUM",
                            "status": "PUBLISHED",
                            "createdByRole": "CONTENT_CREATOR",
                        },
                        {
                            "activityId": 302,
                            "moduleId": 201,
                            "displayOrder": 2,
                            "title": "Fraction Hotspot",
                            "activityType": "HOTSPOT",
                            "difficulty": "MEDIUM",
                            "status": "PUBLISHED",
                            "createdByRole": "CONTENT_CREATOR",
                        },
                        {
                            "activityId": 399,
                            "moduleId": 201,
                            "displayOrder": 3,
                            "title": "Student Generated Quiz",
                            "activityType": "MCQ",
                            "status": "PUBLISHED",
                            "createdByRole": "STUDENT",
                        },
                    ],
                },
            )
        if ":8088/api/v1/progress/summary/user/42" in url:
            return httpx.Response(
                200,
                json={
                    "starsEarned": 25,
                    "mapActivitiesDone": 1,
                    "averageScore": 45.0,
                    "subjectProgress": {
                        "Mathematics": {"percentage": 35.0},
                        "Environmental Studies": {"percentage": 90.0},
                    },
                    "badges": [
                        {"id": "first_quest", "earned": True},
                        {"id": "quest_explorer", "earned": False},
                    ],
                },
            )
        if ":8088/api/v1/progress/activities/user/42" in url:
            return httpx.Response(
                200,
                json=[
                    {
                        "activityId": 301,
                        "moduleId": 201,
                        "subjectName": "Mathematics",
                        "scorePercentage": 45.0,
                        "isPassed": True,
                    }
                ],
            )
        return httpx.Response(404, json={"error": "Not found"})

    return httpx.MockTransport(handler)


class RecommendationRankingAndPipelineTests(unittest.TestCase):
    def test_empty_candidates_returns_empty_list(self) -> None:
        profile = StudentLearningProfile(userId=1)
        analysis = LearningProfileAnalysis()
        self.assertEqual(RecommendationRanker().rank([], profile, analysis), [])

    def test_multi_factor_scoring_deduplication_and_dismissed_filtering(self) -> None:
        profile = StudentLearningProfile(
            userId=42,
            gradeLevel="Grade 4",
            learningStyle="VISUAL",
            difficultyPreference="ADAPTIVE",
            enrolledCourseIds=[101],
            lowScoreActivityIds=[301],
            subjectStats={
                "Mathematics": SubjectLearningStat(
                    subject="Mathematics", averageScore=45.0, attemptCount=1, trend="NEEDS_ATTENTION"
                ),
                "ICT": SubjectLearningStat(subject="ICT", attemptCount=0, trend="NOT_STARTED"),
                "Environmental Studies": SubjectLearningStat(
                    subject="Environmental Studies", masteryPercentage=90.0, averageScore=90.0, attemptCount=2
                ),
            },
        )
        analysis = LearningProfileAnalyzer().analyze(profile)

        retry = RecommendationCandidate(
            recommendationId="map-activity-301",
            itemType="ACTIVITY",
            actionType="RETRY_MAP",
            title="Half & Quarter Quiz",
            description="Retry quiz",
            subject="Mathematics",
            gradeLevel="Grade 4",
            difficulty="MEDIUM",
            activityType="MCQ",
            courseId=101,
            activityId=301,
        )
        # Semantic duplicate for the same activityId with an alternate ID
        retry_semantic_dup = retry.model_copy(
            update={"recommendationId": "alt-activity-301", "difficulty": "HARD"}
        )
        # Exact ID duplicate
        retry_exact_dup = retry.model_copy()

        strong_course = RecommendationCandidate(
            recommendationId="course-109",
            itemType="COURSE",
            actionType="ENROLL",
            title="Advanced Nature",
            description="Strong subject course",
            subject="Environmental Studies",
            gradeLevel="Grade 3",
            difficulty="HARD",
            courseId=109,
        )
        dismissed_course = RecommendationCandidate(
            recommendationId="course-102",
            itemType="COURSE",
            actionType="ENROLL",
            title="Digital Tools",
            description="Untouched ICT",
            subject="ICT",
            gradeLevel="Grade 4",
            difficulty="EASY",
            courseId=102,
        )
        badge_item = RecommendationCandidate(
            recommendationId="badge-quest-first_quest",
            itemType="STUDY_TIP",
            actionType="EARN_BADGE",
            title="Unlock Batch: First Quest",
            description="Pass 1 map quest",
            subject="General",
            gradeLevel="Grade 4",
            difficulty=analysis.recommendedDifficulty,
        )

        candidates = [
            strong_course,
            retry_semantic_dup,
            dismissed_course,
            badge_item,
            retry,
            retry_exact_dup,
        ]
        ranked = RecommendationRanker().rank(
            candidates=candidates,
            profile=profile,
            analysis=analysis,
            dismissed_ids={"course-102"},
        )

        # Dismissed item and both exact/semantic duplicates should be removed
        ranked_ids = [r.recommendationId for r in ranked]
        self.assertNotIn("course-102", ranked_ids)
        self.assertEqual(len(ranked), 3)
        self.assertEqual(ranked_ids[0], "map-activity-301")
        self.assertNotIn("alt-activity-301", ranked_ids)

        # Sequential rank 1..N and valid 0-100 score breakdown
        self.assertEqual([r.rank for r in ranked], [1, 2, 3])
        for item in ranked:
            self.assertGreaterEqual(item.priorityScore, 0.0)
            self.assertLessEqual(item.priorityScore, 100.0)
            self.assertAlmostEqual(
                item.priorityScore, round(sum(item.scoreBreakdown.values()), 1), places=1
            )

        # Original inputs must remain unmutated
        self.assertEqual(retry.rank, 0)
        self.assertEqual(retry.priorityScore, 0.0)

    def test_grade_and_difficulty_fit_scoring_ranks_exact_match_highest(self) -> None:
        profile = StudentLearningProfile(
            userId=7, gradeLevel="Grade 4", learningStyle="INTERACTIVE", difficultyPreference="MEDIUM"
        )
        analysis = LearningProfileAnalysis(
            recommendedDifficulty="MEDIUM",
            badgeOpportunities=[
                BadgeOpportunity(
                    badgeId="quest_explorer",
                    badgeName="Quest Explorer",
                    icon="twemoji:star",
                    requirement="3 quests",
                    progressText="0/3",
                )
            ],
        )
        exact = RecommendationCandidate(
            recommendationId="c-exact",
            itemType="COURSE",
            actionType="ENROLL",
            title="Grade 4 Medium",
            description="Exact fit",
            subject="Mathematics",
            gradeLevel="Grade 4",
            difficulty="MEDIUM",
            courseId=1,
        )
        adjacent = RecommendationCandidate(
            recommendationId="c-adj",
            itemType="COURSE",
            actionType="ENROLL",
            title="Grade 5 Easy",
            description="Adjacent fit",
            subject="Mathematics",
            gradeLevel="Grade 5",
            difficulty="EASY",
            courseId=2,
        )
        far = RecommendationCandidate(
            recommendationId="c-far",
            itemType="COURSE",
            actionType="ENROLL",
            title="Grade 5 Easy vs Grade 3 Hard",
            description="Larger mismatch",
            subject="Mathematics",
            gradeLevel="Grade 5",
            difficulty="HARD",
            courseId=3,
        )

        ranked = RecommendationRanker().rank([far, adjacent, exact], profile, analysis, limit=2)
        self.assertEqual([r.recommendationId for r in ranked], ["c-exact", "c-adj"])
        self.assertEqual(ranked[0].scoreBreakdown["gradeAndDifficultyFit"], 20.0)
        self.assertEqual(ranked[1].scoreBreakdown["gradeAndDifficultyFit"], 11.0)

    def test_end_to_end_pipeline_orchestrator_across_all_five_stages(self) -> None:
        pipeline = RecommendationPipeline(
            collector=StudentDataCollector(transport=_mock_microservices_transport()),
            profile_builder=StudentLearningProfileBuilder(),
            analyzer=LearningProfileAnalyzer(),
            generator=RecommendationGenerator(enable_llm=False),
            ranker=RecommendationRanker(),
        )

        output = asyncio.run(pipeline.run(user_id=42))

        self.assertIsInstance(output, RecommendationToolOutput)
        self.assertEqual(output.userId, 42)
        self.assertTrue(output.generatedAt)
        self.assertTrue(all(v == "ok" for v in output.sourceHealth.values()))
        self.assertEqual(output.profile.studentName, "Nethmi Perera")
        self.assertIn("Mathematics", output.analysis.weakSubjects)

        # Student-created activity 399 and completed course 109 must not appear
        all_ids = [r.recommendationId for r in output.recommendations]
        self.assertNotIn("map-activity-399", all_ids)
        self.assertNotIn("course-109", all_ids)

        # Top recommendation should prioritize Mathematics retry activity (301)
        self.assertEqual(output.recommendations[0].recommendationId, "map-activity-301")
        self.assertEqual(output.recommendations[0].rank, 1)
        self.assertGreater(
            output.recommendations[0].priorityScore,
            output.recommendations[-1].priorityScore,
        )

        # Category projections populated cleanly
        self.assertTrue(len(output.recommendedCourses) >= 1)
        self.assertTrue(len(output.recommendedActivities) >= 2)
        self.assertTrue(len(output.studyTips) >= 1)
        self.assertIn("Mathematics", output.mascotTip)

    def test_cold_start_pipeline_with_offline_microservices_fallback(self) -> None:
        def failing_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Offline", request=request)

        pipeline = RecommendationPipeline(
            collector=StudentDataCollector(transport=httpx.MockTransport(failing_handler)),
            generator=RecommendationGenerator(enable_llm=False),
        )
        ctx = ClientContextPayload(
            studentName="Kasun Silva",
            gradeLevel="Grade 3",
            learningStyle="INTERACTIVE",
            difficultyLevel="ADAPTIVE",
        )

        output = asyncio.run(pipeline.run(user_id=99, client_context=ctx))

        self.assertEqual(output.profile.gradeLevel, "Grade 3")
        self.assertEqual(output.analysis.performanceTier, "STARTER")
        self.assertEqual(output.analysis.recommendedDifficulty, "EASY")
        self.assertEqual(len(output.recommendedCourses), 3)
        self.assertEqual(output.recommendedActivities[0].itemType, "AI_PRACTICE")
        self.assertEqual(output.studyTips[0].actionType, "EARN_BADGE")
        self.assertEqual(output.sourceHealth["userService"], "client_fallback")


if __name__ == "__main__":
    unittest.main(verbosity=2)
