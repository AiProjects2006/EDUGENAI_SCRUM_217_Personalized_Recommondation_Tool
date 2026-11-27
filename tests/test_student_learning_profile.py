"""Tests for Stage 2: Student Learning Profile Builder."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models import ClientContextPayload, CollectedStudentData
from student_learning_profile import (
    StudentLearningProfileBuilder,
    normalize_difficulty,
    normalize_grade,
    normalize_learning_style,
    normalize_subject_name,
)


class StudentLearningProfileTests(unittest.TestCase):
    def test_normalization_helpers(self) -> None:
        self.assertEqual(normalize_grade("Grade 3"), ("Grade 3", "GRADE_3"))
        self.assertEqual(normalize_grade("5"), ("Grade 5", "GRADE_5"))
        self.assertEqual(normalize_grade(None), ("Grade 4", "GRADE_4"))

        self.assertEqual(normalize_subject_name("Math"), "Mathematics")
        self.assertEqual(normalize_subject_name("Digital Safety & ICT"), "ICT")
        self.assertEqual(normalize_subject_name("Environmental Studies"), "Environmental Studies")
        self.assertEqual(normalize_subject_name("Science"), "Environmental Studies")

        self.assertEqual(normalize_learning_style("Hands On"), "INTERACTIVE")
        self.assertEqual(normalize_learning_style("visual"), "VISUAL")
        self.assertEqual(normalize_difficulty("BEGINNER"), "EASY")
        self.assertEqual(normalize_difficulty(None), "ADAPTIVE")

    def test_builds_unified_profile_from_microservice_data(self) -> None:
        data = CollectedStudentData(
            userId=42,
            userProfile={"id": 42, "firstName": "Nethmi", "lastName": "Perera"},
            preferences={"learningStyle": "VISUAL", "difficultyLevel": "MEDIUM"},
            enrollments=[
                {"courseId": 101, "status": "ACTIVE", "studentGrade": "Grade 5"},
                {"courseId": 102, "status": "COMPLETED"},
                {"courseId": 103, "status": "PENDING"},
            ],
            courses=[
                {"courseId": 101, "subject": "Mathematics", "title": "Fractions"},
                {"courseId": 102, "subject": "ICT", "title": "Computers"},
            ],
            modules=[
                {"moduleId": 201, "courseId": 101, "title": "Pizza Fractions"},
                {"moduleId": 202, "courseId": 102, "title": "Input Devices"},
            ],
            activities=[
                {"activityId": 301, "moduleId": 201, "activityType": "MCQ"},
                {"activityId": 302, "moduleId": 201, "activityType": "HOTSPOT"},
                {"activityId": 303, "moduleId": 202, "activityType": "MATCHING"},
            ],
            progressSummary={
                "starsEarned": 35,
                "mapActivitiesDone": 3,
                "practiceActivitiesDone": 1,
                "currentStreakDays": 4,
                "averageScore": 72.5,
                "subjectProgress": {
                    "Mathematics": {"percentage": 40.0},
                    "ICT": {"percentage": 90.0},
                },
                "badges": [
                    {"id": "first_quest", "earned": True},
                    {"id": "bronze_achiever", "earned": True},
                    {"id": "quest_explorer", "earned": True},
                    {"id": "gold_achiever", "earned": False},
                ],
            },
            # Ordered newest first (OrderByCompletedAtDesc)
            progressHistory=[
                {"activityId": 302, "moduleId": 201, "scorePercentage": 55.0, "isPassed": True, "timeSpentMins": 5},
                {"activityId": 301, "moduleId": 201, "scorePercentage": 40.0, "isPassed": True, "timeSpentMins": 3},
                {"activityId": 303, "moduleId": 202, "scorePercentage": 90.0, "isPassed": True, "timeSpentMins": 4},
            ],
        )

        profile = StudentLearningProfileBuilder().build(data)

        self.assertEqual(profile.studentName, "Nethmi Perera")
        self.assertEqual(profile.gradeLevel, "Grade 5")
        self.assertEqual(profile.gradeEnum, "GRADE_5")
        self.assertEqual(profile.learningStyle, "VISUAL")
        self.assertEqual(profile.difficultyPreference, "MEDIUM")
        self.assertEqual(profile.enrolledCourseIds, [101, 102])
        self.assertEqual(profile.completedCourseIds, [102])
        self.assertEqual(profile.pendingCourseIds, [103])
        self.assertEqual(profile.starsEarned, 35)
        self.assertEqual(profile.averageScore, 72.5)
        self.assertEqual(profile.currentStreakDays, 4)

        math_stat = profile.subjectStats["Mathematics"]
        self.assertEqual(math_stat.attemptCount, 2)
        self.assertEqual(math_stat.averageScore, 47.5)
        self.assertEqual(math_stat.lastScore, 55.0)
        self.assertEqual(math_stat.totalTimeSpentMins, 8)
        self.assertEqual(math_stat.trend, "IMPROVING")

        self.assertEqual(profile.subjectStats["Environmental Studies"].trend, "NOT_STARTED")
        self.assertEqual(profile.questionTypeStats["MATCHING"]["averageScore"], 90.0)
        self.assertEqual(profile.completedActivityIds, [301, 302, 303])
        self.assertEqual(profile.lowScoreActivityIds, [301, 302])
        self.assertEqual(profile.earnedBadges, ["first_quest", "bronze_achiever", "quest_explorer"])
        self.assertEqual(profile.lockedBadges, ["gold_achiever"])

    def test_client_context_fallback_and_deduplication(self) -> None:
        data = CollectedStudentData(
            userId=15,
            clientContext=ClientContextPayload(
                studentName="Kasun",
                gradeLevel="Grade 3",
                learningStyle="Analytical",
                difficultyLevel="Easy",
                preferredSubjects=["English"],
                starsEarned=10,
                completedMapActivities={
                    "act-401": {"activityId": 401, "subject": "Mathematics", "percentage": 35.0, "passed": False}
                },
                recentScores=[
                    {"activityId": 401, "subject": "Mathematics", "percentage": 35.0, "activityType": "MCQ"}
                ],
                badges=[{"id": "first_quest", "earned": False}],
            ),
        )

        profile = StudentLearningProfileBuilder().build(data)

        self.assertEqual(profile.studentName, "Kasun")
        self.assertEqual(profile.gradeLevel, "Grade 3")
        self.assertEqual(profile.learningStyle, "ANALYTICAL")
        self.assertEqual(profile.difficultyPreference, "EASY")
        self.assertIn("English", profile.subjectStats)
        self.assertEqual(profile.subjectStats["Mathematics"].attemptCount, 1)
        self.assertEqual(profile.subjectStats["Mathematics"].trend, "NEEDS_ATTENTION")
        self.assertEqual(profile.completedActivityIds, [])
        self.assertEqual(profile.lowScoreActivityIds, [401])
        self.assertEqual(profile.bestScoreByActivityId["401"], 35.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
