"""Tests for Stage 3: Learning Profile Analysis."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from learning_profile_analysis import LearningProfileAnalyzer
from models import StudentLearningProfile, SubjectLearningStat


class LearningProfileAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.analyzer = LearningProfileAnalyzer()

    def test_detects_weak_strong_untouched_subjects_and_badge_proximity(self) -> None:
        profile = StudentLearningProfile(
            userId=42,
            gradeLevel="Grade 4",
            learningStyle="VISUAL",
            difficultyPreference="ADAPTIVE",
            starsEarned=26,
            averageScore=52.0,
            mapActivitiesDone=2,
            practiceActivitiesDone=1,
            subjectStats={
                "Mathematics": SubjectLearningStat(
                    subject="Mathematics",
                    masteryPercentage=30.0,
                    attemptCount=2,
                    passedCount=1,
                    averageScore=45.0,
                    trend="NEEDS_ATTENTION",
                ),
                "Environmental Studies": SubjectLearningStat(
                    subject="Environmental Studies",
                    masteryPercentage=82.0,
                    attemptCount=2,
                    passedCount=2,
                    averageScore=86.0,
                    trend="IMPROVING",
                ),
                "ICT": SubjectLearningStat(
                    subject="ICT",
                    masteryPercentage=0.0,
                    attemptCount=0,
                    trend="NOT_STARTED",
                ),
            },
            questionTypeStats={
                "FILL_BLANK": {"attempts": 2, "averageScore": 40.0},
                "HOTSPOT": {"attempts": 1, "averageScore": 85.0},
            },
            earnedBadges=["first_quest", "bronze_achiever"],
            lowScoreActivityIds=[301],
            bestScoreByActivityId={"301": 45.0},
        )

        analysis = self.analyzer.analyze(profile)

        self.assertEqual(analysis.performanceTier, "DEVELOPING")
        self.assertEqual(analysis.recommendedDifficulty, "EASY")
        self.assertEqual(analysis.weakSubjects, ["Mathematics"])
        self.assertEqual(analysis.strongSubjects, ["Environmental Studies"])
        self.assertEqual(analysis.untouchedSubjects, ["ICT"])
        # Weak question format FILL_BLANK prioritized alongside VISUAL formats
        self.assertEqual(analysis.preferredQuestionTypes[0], "FILL_BLANK")
        self.assertIn("HOTSPOT", analysis.preferredQuestionTypes)
        # 2/3 map done -> quest_explorer should be highest urgency (0.90)
        self.assertEqual(analysis.badgeOpportunities[0].badgeId, "quest_explorer")
        self.assertIn("Mathematics", analysis.insightHeadline)

    def test_explicit_hard_preference_steps_down_when_struggling(self) -> None:
        profile = StudentLearningProfile(
            userId=10,
            difficultyPreference="HARD",
            averageScore=42.0,
            mapActivitiesDone=1,
        )
        analysis = self.analyzer.analyze(profile)
        self.assertEqual(analysis.recommendedDifficulty, "MEDIUM")

    def test_starter_and_advanced_tiers(self) -> None:
        starter = StudentLearningProfile(userId=1, gradeLevel="Grade 3", difficultyPreference="ADAPTIVE")
        starter_analysis = self.analyzer.analyze(starter)
        self.assertEqual(starter_analysis.performanceTier, "STARTER")
        self.assertEqual(starter_analysis.recommendedDifficulty, "EASY")
        self.assertEqual(starter_analysis.badgeOpportunities[0].badgeId, "first_quest")

        advanced = StudentLearningProfile(
            userId=2,
            gradeLevel="Grade 5",
            learningStyle="ANALYTICAL",
            difficultyPreference="ADAPTIVE",
            averageScore=91.0,
            starsEarned=80,
            mapActivitiesDone=4,
            earnedBadges=["first_quest", "bronze_achiever", "silver_achiever", "gold_achiever", "quest_explorer"],
            bestScoreByActivityId={"1": 91.0},
            subjectStats={
                "Mathematics": SubjectLearningStat(
                    subject="Mathematics", masteryPercentage=90.0, attemptCount=3, averageScore=91.0, trend="STEADY"
                )
            },
        )
        adv_analysis = self.analyzer.analyze(advanced)
        self.assertEqual(adv_analysis.performanceTier, "ADVANCED")
        self.assertEqual(adv_analysis.recommendedDifficulty, "HARD")
        self.assertEqual(adv_analysis.preferredQuestionTypes[0], "PROBLEM_SOLVING")
        badge_ids = [b.badgeId for b in adv_analysis.badgeOpportunities]
        self.assertIn("diamond_master", badge_ids)


if __name__ == "__main__":
    unittest.main(verbosity=2)
