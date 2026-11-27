"""Tests for Stage 4: Recommendation Generation."""

from dataclasses import replace
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import settings
from learning_profile_analysis import LearningProfileAnalyzer
from models import CollectedStudentData
from recommendation_generation import RecommendationGenerator
from student_learning_profile import StudentLearningProfileBuilder


def _build_stage1_to_3_fixtures():
    data = CollectedStudentData(
        userId=42,
        userProfile={"id": 42, "firstName": "Nethmi", "lastName": "Perera"},
        preferences={"learningStyle": "VISUAL", "difficultyLevel": "ADAPTIVE"},
        enrollments=[
            {"enrollmentId": 10, "userId": 42, "courseId": 101, "status": "ACTIVE", "studentGrade": "Grade 4"},
            {"enrollmentId": 11, "userId": 42, "courseId": 109, "status": "COMPLETED"},
        ],
        subjects=[
            {"subjectId": 1, "name": "Mathematics"},
            {"subjectId": 2, "name": "ICT"},
            {"subjectId": 3, "name": "Environmental Studies"},
        ],
        courses=[
            {"courseId": 101, "subjectId": 1, "title": "Fractions & Decimals", "gradeLevel": "Grade 4", "level": "INTERMEDIATE", "status": "PUBLISHED"},
            {"courseId": 102, "subjectId": 2, "title": "Digital Tools", "gradeLevel": "Grade 4", "level": "BEGINNER", "status": "PUBLISHED"},
            {"courseId": 109, "subjectId": 3, "title": "Completed Nature Course", "gradeLevel": "Grade 4", "status": "PUBLISHED"},
        ],
        modules=[
            {"moduleId": 201, "courseId": 101, "title": "Pizza Fractions"},
            {"moduleId": 202, "courseId": 102, "title": "Safe Browsing"},
        ],
        activities=[
            {"activityId": 301, "moduleId": 201, "displayOrder": 1, "title": "Half & Quarter Quiz", "activityType": "MCQ", "difficulty": "MEDIUM", "status": "PUBLISHED", "createdByRole": "CONTENT_CREATOR"},
            {"activityId": 302, "moduleId": 201, "displayOrder": 2, "title": "Fraction Hotspot", "activityType": "HOTSPOT", "difficulty": "MEDIUM", "status": "PUBLISHED", "createdByRole": "CONTENT_CREATOR"},
            {"activityId": 399, "moduleId": 201, "displayOrder": 3, "title": "Student Generated Quiz", "activityType": "MCQ", "status": "PUBLISHED", "createdByRole": "STUDENT"},
        ],
        progressSummary={
            "starsEarned": 25,
            "mapActivitiesDone": 1,
            "averageScore": 45.0,
            "subjectProgress": {"Mathematics": {"percentage": 35.0}, "Environmental Studies": {"percentage": 90.0}},
            "badges": [{"id": "first_quest", "earned": True}, {"id": "quest_explorer", "earned": False}],
        },
        progressHistory=[
            {"activityId": 301, "moduleId": 201, "subjectName": "Mathematics", "scorePercentage": 45.0, "isPassed": True},
        ],
    )
    profile = StudentLearningProfileBuilder().build(data)
    analysis = LearningProfileAnalyzer().analyze(profile)
    return data, profile, analysis


class RecommendationGenerationTests(unittest.TestCase):
    def test_generates_all_candidate_categories_and_excludes_completed_or_student_items(self) -> None:
        data, profile, analysis = _build_stage1_to_3_fixtures()
        gen = RecommendationGenerator(enable_llm=False)

        candidates, mascot_tip = gen.generate(data, profile, analysis)

        self.assertEqual(mascot_tip, analysis.insightHeadline)

        by_id = {c.recommendationId: c for c in candidates}
        # Course 101 is enrolled -> RESUME; Course 102 is not enrolled -> ENROLL; Course 109 completed -> excluded
        self.assertEqual(by_id["course-101"].actionType, "RESUME")
        self.assertEqual(by_id["course-102"].actionType, "ENROLL")
        self.assertNotIn("course-109", by_id)

        # Map activity 301 scored 45% (<60%) -> RETRY_MAP; 302 uncompleted -> PLAY_MAP; student 399 excluded
        self.assertEqual(by_id["map-activity-301"].actionType, "RETRY_MAP")
        self.assertEqual(by_id["map-activity-302"].actionType, "PLAY_MAP")
        self.assertNotIn("map-activity-399", by_id)

        # AI Practice and Study/Badge Quests generated
        ai_items = [c for c in candidates if c.itemType == "AI_PRACTICE"]
        study_items = [c for c in candidates if c.itemType == "STUDY_TIP"]
        self.assertTrue(any(c.subject == "Mathematics" for c in ai_items))
        self.assertTrue(any(c.actionType == "REVIEW_NOTES" for c in study_items))
        self.assertTrue(any(c.actionType == "EARN_BADGE" for c in study_items))

    def test_cold_start_starter_courses_when_catalog_empty(self) -> None:
        data = CollectedStudentData(userId=99)
        profile = StudentLearningProfileBuilder().build(data)
        analysis = LearningProfileAnalyzer().analyze(profile)

        candidates, mascot_tip = RecommendationGenerator(enable_llm=False).generate(data, profile, analysis)

        starter_courses = [c for c in candidates if c.recommendationId.startswith("starter-course-")]
        self.assertEqual(len(starter_courses), 3)
        self.assertTrue(all(c.actionType == "ENROLL" for c in starter_courses))
        self.assertIn("Grade 4", mascot_tip)

    def test_llm_mascot_insight_uses_mock_gemini_and_falls_back_on_error(self) -> None:
        data, profile, analysis = _build_stage1_to_3_fixtures()

        def fake_gemini_ok(_key: str):
            return SimpleNamespace(
                models=SimpleNamespace(
                    generate_content=lambda **_kw: SimpleNamespace(
                        text='"Swim into Fractions Hotspot next to boost Math and unlock Quest Explorer!"'
                    )
                )
            )

        patched_settings = replace(settings, gemini_api_key="fake-gemini", openai_api_key="")
        with patch("recommendation_generation.settings", patched_settings):
            gen_ok = RecommendationGenerator(enable_llm=True, gemini_client_factory=fake_gemini_ok)
            _, tip_ok = gen_ok.generate(data, profile, analysis)
            self.assertEqual(tip_ok, "Swim into Fractions Hotspot next to boost Math and unlock Quest Explorer!")

            def fake_gemini_fail(_key: str):
                raise RuntimeError("Quota exceeded")

            gen_fail = RecommendationGenerator(enable_llm=True, gemini_client_factory=fake_gemini_fail)
            _, tip_fallback = gen_fail.generate(data, profile, analysis)
            self.assertEqual(tip_fallback, analysis.insightHeadline)


if __name__ == "__main__":
    unittest.main(verbosity=2)
