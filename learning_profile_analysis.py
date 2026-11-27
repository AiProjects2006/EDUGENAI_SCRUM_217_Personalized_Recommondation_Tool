"""Stage 3: Learning Profile Analysis (Strengths, Gaps, Readiness & Badge Proximity)."""

from __future__ import annotations

from typing import Dict, List, Tuple

from models import (
    BadgeOpportunity,
    LearningProfileAnalysis,
    StudentLearningProfile,
    SubjectLearningStat,
)

STYLE_TO_QUESTION_TYPES: Dict[str, List[str]] = {
    "VISUAL": ["HOTSPOT", "MATCHING", "SORTING", "MCQ"],
    "INTERACTIVE": ["DRAG_DROP", "SORTING", "MATCHING", "TIMED_QUIZ"],
    "STEP_BY_STEP": ["TRUE_FALSE", "FILL_BLANK", "MCQ", "SHORT_ANSWER"],
    "PRACTICE_FIRST": ["MCQ", "TIMED_QUIZ", "CHALLENGE_QUIZ", "TRUE_FALSE"],
    "ANALYTICAL": ["PROBLEM_SOLVING", "APPLICATION_BASED", "SHORT_ANSWER", "ESSAY"],
}


def _classify_performance_tier(profile: StudentLearningProfile) -> str:
    total_acts = profile.mapActivitiesDone + profile.practiceActivitiesDone
    avg = profile.averageScore
    if total_acts == 0 and avg == 0:
        return "STARTER"
    if avg >= 85 and profile.mapActivitiesDone >= 2:
        return "ADVANCED"
    if avg >= 65:
        return "PROFICIENT"
    return "DEVELOPING"


def _determine_recommended_difficulty(profile: StudentLearningProfile) -> str:
    avg = profile.averageScore
    total_acts = profile.mapActivitiesDone + profile.practiceActivitiesDone
    if profile.difficultyPreference in {"EASY", "MEDIUM", "HARD"}:
        if profile.difficultyPreference == "HARD" and 0 < avg < 50:
            return "MEDIUM"
        return profile.difficultyPreference
    if total_acts == 0:
        return "EASY"
    if avg >= 80:
        return "HARD"
    if avg >= 55:
        return "MEDIUM"
    return "EASY"


def _classify_subjects(
    subject_stats: Dict[str, SubjectLearningStat],
) -> Tuple[List[str], List[str], List[str]]:
    strong: List[str] = []
    weak: List[str] = []
    untouched: List[str] = []

    for subj in sorted(subject_stats.keys()):
        if subj == "General":
            continue
        stat = subject_stats[subj]
        if stat.attemptCount == 0 and stat.masteryPercentage == 0:
            untouched.append(subj)
        elif (stat.attemptCount > 0 and stat.averageScore < 60.0) or stat.trend == "NEEDS_ATTENTION":
            weak.append(subj)
        elif stat.averageScore >= 75.0 or stat.masteryPercentage >= 70.0:
            strong.append(subj)

    return strong, weak, untouched


def _select_preferred_question_types(
    learning_style: str,
    question_type_stats: Dict[str, Dict[str, object]],
) -> List[str]:
    selected = list(STYLE_TO_QUESTION_TYPES.get(learning_style, STYLE_TO_QUESTION_TYPES["INTERACTIVE"]))
    weak_formats = sorted(
        (
            (qtype, float(qmeta.get("averageScore", 100.0)))  # type: ignore[arg-type]
            for qtype, qmeta in question_type_stats.items()
            if float(qmeta.get("averageScore", 100.0)) < 60.0  # type: ignore[arg-type]
        ),
        key=lambda item: item[1],
    )
    for qtype, _ in reversed(weak_formats):
        if qtype not in selected:
            selected.insert(0, qtype)
    return selected[:4]


def _compute_badge_opportunities(profile: StudentLearningProfile) -> List[BadgeOpportunity]:
    earned = set(profile.earnedBadges)
    opportunities: List[BadgeOpportunity] = []

    if "first_quest" not in earned:
        opportunities.append(
            BadgeOpportunity(
                badgeId="first_quest",
                badgeName="First Quest",
                icon="twemoji:star",
                requirement="Pass 1 Activity Map exercise (40%+)",
                progressText=f"{profile.mapActivitiesDone}/1 map quests passed",
                urgency=0.98,
            )
        )
    elif "quest_explorer" not in earned:
        remaining = max(0, 3 - profile.mapActivitiesDone)
        opportunities.append(
            BadgeOpportunity(
                badgeId="quest_explorer",
                badgeName="Quest Explorer",
                icon="twemoji:glowing-star",
                requirement="Complete 3 Activity Map exercises",
                progressText=f"{profile.mapActivitiesDone}/3 complete ({remaining} left)",
                urgency=0.90 if remaining == 1 else 0.78,
            )
        )

    best_map_score = max(profile.bestScoreByActivityId.values(), default=profile.averageScore)
    if "bronze_achiever" not in earned and 0 < best_map_score < 40:
        opportunities.append(
            BadgeOpportunity(
                badgeId="bronze_achiever",
                badgeName="Bronze Starter",
                icon="twemoji:3rd-place-medal",
                requirement="Score 40%+ on an Activity Map exercise",
                progressText=f"Best map score: {round(best_map_score)}%",
                urgency=0.92,
            )
        )
    elif "silver_achiever" not in earned and best_map_score >= 40:
        opportunities.append(
            BadgeOpportunity(
                badgeId="silver_achiever",
                badgeName="Silver Explorer",
                icon="twemoji:2nd-place-medal",
                requirement="Score 60%+ on an Activity Map exercise",
                progressText=f"Best map score: {round(best_map_score)}%",
                urgency=0.84,
            )
        )
    elif "gold_achiever" not in earned and best_map_score >= 60:
        opportunities.append(
            BadgeOpportunity(
                badgeId="gold_achiever",
                badgeName="Gold Achiever",
                icon="twemoji:1st-place-medal",
                requirement="Score 80%+ on an Activity Map exercise",
                progressText=f"Best map score: {round(best_map_score)}%",
                urgency=0.82,
            )
        )
    elif "diamond_master" not in earned and best_map_score >= 80:
        opportunities.append(
            BadgeOpportunity(
                badgeId="diamond_master",
                badgeName="Diamond Mastery",
                icon="twemoji:gem-stone",
                requirement="Score 90%+ on an Activity Map exercise",
                progressText=f"Best map score: {round(best_map_score)}%",
                urgency=0.80,
            )
        )

    if "module_champion" not in earned:
        opportunities.append(
            BadgeOpportunity(
                badgeId="module_champion",
                badgeName="Module Champion",
                icon="twemoji:trophy",
                requirement="Complete all uploaded activities in a module",
                progressText="Finish a module's Activity Map path",
                urgency=0.76,
            )
        )

    star_targets = [
        ("math", "Math Whiz", "twemoji:abacus", 30, "Score 60%+ in Math or earn 30+ stars"),
        ("ict", "ICT Wizard", "twemoji:laptop", 60, "Score 60%+ in ICT or earn 60+ stars"),
        (
            "environmental",
            "Eco Champion",
            "twemoji:seedling",
            100,
            "Score 60%+ in Science/Env or earn 100+ stars",
        ),
    ]
    for bid, bname, icon, target_stars, req_text in star_targets:
        if bid not in earned:
            ratio = min(1.0, profile.starsEarned / float(target_stars))
            opportunities.append(
                BadgeOpportunity(
                    badgeId=bid,
                    badgeName=bname,
                    icon=icon,
                    requirement=req_text,
                    progressText=f"{profile.starsEarned}/{target_stars} stars collected",
                    urgency=round(0.60 + 0.35 * ratio, 2),
                )
            )

    opportunities.sort(key=lambda b: b.urgency, reverse=True)
    return opportunities[:4]


def _build_notes_and_headline(
    profile: StudentLearningProfile,
    rec_diff: str,
    strong: List[str],
    weak: List[str],
    untouched: List[str],
    opportunities: List[BadgeOpportunity],
) -> Tuple[str, List[str]]:
    notes: List[str] = []
    if weak:
        notes.append(f"Focus needed in {', '.join(weak)} to lift scores above 60%.")
    if profile.lowScoreActivityIds:
        notes.append(
            f"{len(profile.lowScoreActivityIds)} Activity Map exercise(s) scored below 60% and are great candidates for a higher-star retry."
        )
    if strong:
        notes.append(f"Strong mastery in {', '.join(strong)} — ready for {rec_diff.lower()} challenges.")
    if untouched:
        notes.append(f"New subjects ready to explore: {', '.join(untouched)}.")
    if opportunities:
        top_b = opportunities[0]
        notes.append(f"Next batch goal: {top_b.badgeName} ({top_b.progressText}).")

    style_label = profile.learningStyle.lower().replace("_", " ")
    if weak:
        headline = (
            f"Boost your skills in {weak[0]} with {rec_diff.lower()}-level quests "
            f"tailored to your {style_label} style."
        )
    elif strong:
        headline = (
            f"Awesome momentum in {', '.join(strong)}! Step up to {rec_diff.lower()} "
            "challenges and unlock your next batch."
        )
    else:
        headline = (
            f"Ready to explore {profile.gradeLevel}! Start with {rec_diff.lower()} "
            f"quests picked for your {style_label} style."
        )

    return headline, notes


class LearningProfileAnalyzer:
    """Analyzes a StudentLearningProfile to identify gaps, difficulty fit, and next badges."""

    def analyze(self, profile: StudentLearningProfile) -> LearningProfileAnalysis:
        tier = _classify_performance_tier(profile)
        rec_diff = _determine_recommended_difficulty(profile)
        strong, weak, untouched = _classify_subjects(profile.subjectStats)
        preferred_qtypes = _select_preferred_question_types(
            profile.learningStyle,
            profile.questionTypeStats,
        )
        opportunities = _compute_badge_opportunities(profile)
        headline, notes = _build_notes_and_headline(
            profile=profile,
            rec_diff=rec_diff,
            strong=strong,
            weak=weak,
            untouched=untouched,
            opportunities=opportunities,
        )

        return LearningProfileAnalysis(
            performanceTier=tier,  # type: ignore[arg-type]
            recommendedDifficulty=rec_diff,  # type: ignore[arg-type]
            strongSubjects=strong,
            weakSubjects=weak,
            untouchedSubjects=untouched,
            preferredQuestionTypes=preferred_qtypes,
            badgeOpportunities=opportunities,
            insightHeadline=headline,
            analysisNotes=notes,
        )
