"""Stage 5: Multi-Factor Recommendation Scoring, Deduplication, and Ranking."""

from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from learning_profile_analysis import STYLE_TO_QUESTION_TYPES
from models import (
    LearningProfileAnalysis,
    RecommendationCandidate,
    StudentLearningProfile,
)
from student_learning_profile import normalize_grade

_DIFFICULTY_ORDER: Dict[str, int] = {"EASY": 0, "MEDIUM": 1, "HARD": 2}
_ITEM_TYPE_ORDER: Dict[str, int] = {
    "ACTIVITY": 0,
    "COURSE": 1,
    "AI_PRACTICE": 2,
    "STUDY_TIP": 3,
}
_QUEST_BADGE_IDS = frozenset(
    {
        "first_quest",
        "quest_explorer",
        "module_champion",
        "bronze_achiever",
        "silver_achiever",
        "gold_achiever",
        "diamond_master",
    }
)
_SUBJECT_BADGE_MAP: Dict[str, str] = {
    "Mathematics": "math",
    "ICT": "ict",
    "Environmental Studies": "environmental",
}


def _parse_grade_number(raw: Optional[str]) -> int:
    display, _ = normalize_grade(raw)
    return int(display.split()[-1])


def _weakness_urgency_score(
    item: RecommendationCandidate,
    analysis: LearningProfileAnalysis,
) -> float:
    """Factor 1 (0-35): Remediation & subject-gap urgency."""
    if item.actionType == "RETRY_MAP":
        return 35.0 if item.subject in analysis.weakSubjects else 34.0
    if item.actionType == "REVIEW_NOTES":
        return 26.0
    if item.subject in analysis.weakSubjects:
        return 30.0
    if item.subject in analysis.untouchedSubjects:
        return 18.0
    if item.subject in analysis.strongSubjects:
        return 10.0
    return 14.0


def _curriculum_continuity_score(
    item: RecommendationCandidate,
    profile: StudentLearningProfile,
) -> float:
    """Factor 2 (0-25): Active enrollment & sequential quest progression."""
    if item.actionType in {"PLAY_MAP", "RETRY_MAP"}:
        return 25.0 if item.courseId in profile.enrolledCourseIds else 20.0
    if item.actionType == "RESUME":
        return 23.0
    if item.actionType == "GENERATE_PRACTICE":
        return 17.0
    if item.actionType == "ENROLL":
        if item.courseId is not None and item.courseId in profile.pendingCourseIds:
            return 11.0
        return 15.0
    return 12.0


def _grade_and_difficulty_fit_score(
    item: RecommendationCandidate,
    profile: StudentLearningProfile,
    analysis: LearningProfileAnalysis,
) -> float:
    """Factor 3 (0-20): Grade-level match (0-10) + adaptive difficulty fit (0-10)."""
    grade_delta = abs(
        _parse_grade_number(item.gradeLevel) - _parse_grade_number(profile.gradeLevel)
    )
    if grade_delta == 0:
        grade_fit = 10.0
    elif grade_delta == 1:
        grade_fit = 5.0
    else:
        grade_fit = 2.0

    item_diff = _DIFFICULTY_ORDER.get(item.difficulty, 1)
    rec_diff = _DIFFICULTY_ORDER.get(analysis.recommendedDifficulty, 1)
    diff_delta = abs(item_diff - rec_diff)
    if diff_delta == 0:
        diff_fit = 10.0
    elif diff_delta == 1:
        diff_fit = 6.0
    else:
        diff_fit = 2.0

    return grade_fit + diff_fit


def _learning_style_match_score(
    item: RecommendationCandidate,
    profile: StudentLearningProfile,
    preferred_qtypes: List[str],
) -> float:
    """Factor 4 (0-10): Learning-style & preferred activity-format alignment."""
    if item.activityType and item.activityType in preferred_qtypes:
        idx = preferred_qtypes.index(item.activityType)
        return float(max(6, 10 - idx))
    if item.actionType == "REVIEW_NOTES" and profile.learningStyle in {"VISUAL", "STEP_BY_STEP"}:
        return 9.0
    if item.itemType == "COURSE":
        return 7.0
    return 5.0


def _badge_opportunity_score(
    item: RecommendationCandidate,
    analysis: LearningProfileAnalysis,
) -> float:
    """Factor 5 (0-10): Proximity to next unlockable permanent batch/badge."""
    if item.actionType == "EARN_BADGE":
        return 10.0
    opportunity_ids = {b.badgeId for b in analysis.badgeOpportunities}
    if item.itemType == "ACTIVITY" and (_QUEST_BADGE_IDS & opportunity_ids):
        return 9.0
    if (
        item.itemType in {"AI_PRACTICE", "COURSE"}
        and _SUBJECT_BADGE_MAP.get(item.subject) in opportunity_ids
    ):
        return 7.0
    return 3.0


def _semantic_dedup_key(item: RecommendationCandidate) -> Tuple[Any, ...]:
    if item.itemType == "COURSE" and item.courseId is not None:
        return ("COURSE", item.courseId)
    if item.itemType == "ACTIVITY" and item.activityId is not None:
        return ("ACTIVITY", item.activityId)
    return (
        item.itemType,
        item.actionType,
        item.subject.lower(),
        (item.activityType or "").upper(),
        item.title.strip().lower(),
    )


class RecommendationRanker:
    """Scores (0-100), deduplicates, and ranks RecommendationCandidates."""

    def rank(
        self,
        candidates: List[RecommendationCandidate],
        profile: StudentLearningProfile,
        analysis: LearningProfileAnalysis,
        dismissed_ids: Optional[Set[str]] = None,
        limit: Optional[int] = None,
    ) -> List[RecommendationCandidate]:
        if not candidates:
            return []

        dismissed = dismissed_ids or set()
        preferred_qtypes = analysis.preferredQuestionTypes or STYLE_TO_QUESTION_TYPES.get(
            profile.learningStyle, []
        )

        scored: List[RecommendationCandidate] = []
        for item in candidates:
            if item.recommendationId in dismissed:
                continue

            breakdown: Dict[str, float] = {
                "weaknessUrgency": _weakness_urgency_score(item, analysis),
                "curriculumContinuity": _curriculum_continuity_score(item, profile),
                "gradeAndDifficultyFit": _grade_and_difficulty_fit_score(
                    item, profile, analysis
                ),
                "learningStyleMatch": _learning_style_match_score(
                    item, profile, preferred_qtypes
                ),
                "badgeOpportunity": _badge_opportunity_score(item, analysis),
            }
            total = round(min(100.0, max(0.0, sum(breakdown.values()))), 1)
            scored.append(
                item.model_copy(
                    update={
                        "priorityScore": total,
                        "scoreBreakdown": breakdown,
                    }
                )
            )

        scored.sort(
            key=lambda r: (
                -r.priorityScore,
                _ITEM_TYPE_ORDER.get(r.itemType, 9),
                r.title.lower(),
                r.recommendationId,
            )
        )

        deduped: List[RecommendationCandidate] = []
        seen_ids: Set[str] = set()
        seen_semantic: Set[Tuple[Any, ...]] = set()
        for item in scored:
            sem_key = _semantic_dedup_key(item)
            if item.recommendationId in seen_ids or sem_key in seen_semantic:
                continue
            seen_ids.add(item.recommendationId)
            seen_semantic.add(sem_key)
            deduped.append(item.model_copy(update={"rank": len(deduped) + 1}))

        if limit is not None and limit >= 0:
            return deduped[:limit]
        return deduped
