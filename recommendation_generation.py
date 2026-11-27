"""Stage 4: Recommendation Generation (Courses, Map Activities, AI Practice & Study Tips)."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from config import settings
from models import (
    CollectedStudentData,
    LearningProfileAnalysis,
    RecommendationCandidate,
    StudentLearningProfile,
)
from student_data_collection import is_creator_published_activity
from student_learning_profile import CORE_SUBJECTS, normalize_grade, normalize_subject_name

log = logging.getLogger(__name__)

SUBJECT_ICON_MAP: Dict[str, str] = {
    "Mathematics": "twemoji:abacus",
    "ICT": "twemoji:laptop",
    "Environmental Studies": "twemoji:deciduous-tree",
    "English": "twemoji:open-book",
    "General": "twemoji:books",
}

QTYPE_LABEL_MAP: Dict[str, str] = {
    "MCQ": "Multiple Choice (MCQ)",
    "TRUE_FALSE": "True / False",
    "FILL_BLANK": "Fill in the Blanks",
    "MATCHING": "Match the Following",
    "SORTING": "Category Sorting",
    "DRAG_DROP": "Drag & Drop Order",
    "HOTSPOT": "Hotspot Activity",
    "SHORT_ANSWER": "Short Answer",
    "ESSAY": "Structured Essay",
    "PROBLEM_SOLVING": "Problem Solving Exercise",
    "APPLICATION_BASED": "Application-Based Questions",
    "TIMED_QUIZ": "Timed Quiz",
    "CHALLENGE_QUIZ": "Challenge Quiz",
}

_PUBLISHED_COURSE_STATUSES = {"PUBLISHED", "APPROVED", "UNLOCKED", ""}
_COURSE_LEVEL_MAP = {"BEGINNER": "EASY", "ADVANCED": "HARD"}


def _course_subject(course: Dict[str, Any], subject_name_by_id: Dict[Any, str]) -> str:
    raw = (
        course.get("subject")
        or subject_name_by_id.get(course.get("subjectId"))
        or course.get("title")
    )
    return normalize_subject_name(raw)


def _index_catalog(
    data: CollectedStudentData,
) -> Tuple[
    Dict[Any, str],
    List[Dict[str, Any]],
    Dict[int, Dict[str, Any]],
    Dict[int, Dict[str, Any]],
    Dict[int, List[Dict[str, Any]]],
    Dict[int, List[Dict[str, Any]]],
]:
    subject_name_by_id = {
        s.get("subjectId"): s.get("name")
        for s in data.subjects
        if isinstance(s, dict) and s.get("subjectId") and s.get("name")
    }
    courses = [
        c
        for c in data.courses
        if isinstance(c, dict)
        and str(c.get("status") or "PUBLISHED").upper() in _PUBLISHED_COURSE_STATUSES
    ]
    course_map: Dict[int, Dict[str, Any]] = {}
    for c in courses:
        cid = c.get("courseId") or c.get("id")
        if cid:
            course_map[int(cid)] = c

    module_map: Dict[int, Dict[str, Any]] = {}
    modules_by_course: Dict[int, List[Dict[str, Any]]] = {}
    for m in data.modules:
        if not isinstance(m, dict) or not (m.get("moduleId") or m.get("id")):
            continue
        mid = int(m.get("moduleId") or m.get("id"))
        module_map[mid] = m
        if m.get("courseId"):
            modules_by_course.setdefault(int(m["courseId"]), []).append(m)

    activities_by_module: Dict[int, List[Dict[str, Any]]] = {}
    for act in data.activities:
        if not is_creator_published_activity(act):
            continue
        mid = act.get("moduleId")
        if mid:
            activities_by_module.setdefault(int(mid), []).append(act)

    for mid in activities_by_module:
        activities_by_module[mid].sort(
            key=lambda a: (int(a.get("displayOrder") or 999), int(a.get("activityId") or 0))
        )

    return (
        subject_name_by_id,
        courses,
        course_map,
        module_map,
        modules_by_course,
        activities_by_module,
    )


def _generate_course_candidates(
    courses: List[Dict[str, Any]],
    subject_name_by_id: Dict[Any, str],
    profile: StudentLearningProfile,
    analysis: LearningProfileAnalysis,
) -> List[RecommendationCandidate]:
    results: List[RecommendationCandidate] = []
    style_label = profile.learningStyle.lower().replace("_", " ")

    for c in courses:
        cid = c.get("courseId") or c.get("id")
        if not cid or int(cid) in profile.completedCourseIds:
            continue
        cid_int = int(cid)
        subj = _course_subject(c, subject_name_by_id)
        title = str(c.get("title") or c.get("name") or f"Course {cid_int}").strip()
        c_grade, _ = normalize_grade(c.get("gradeLevel") or profile.gradeLevel)
        mapped_diff = _COURSE_LEVEL_MAP.get(str(c.get("level") or "").upper(), "MEDIUM")
        is_enrolled = cid_int in profile.enrolledCourseIds
        is_pending = cid_int in profile.pendingCourseIds
        subj_stat = profile.subjectStats.get(subj)

        if is_enrolled:
            action = "RESUME"
            target_path = "/modules"
            nav_state: Dict[str, Any] = {"course": title, "courseId": cid_int, "subject": subj}
            if subj in analysis.weakSubjects:
                reason = (
                    f"Focus area: your {subj} score ({subj_stat.averageScore if subj_stat else 0}%) "
                    "can improve by resuming this course."
                )
            else:
                reason = (
                    f"Continue your enrolled {subj} course to finish modules and unlock Module Champion."
                )
        else:
            action = "ENROLL"
            target_path = "/courses"
            nav_state = {"category": subj}
            if is_pending:
                reason = f"Enrollment pending approval — check status under {subj}."
            elif subj in analysis.weakSubjects:
                reason = f"Recommended to strengthen {subj} skills at {c_grade}."
            elif subj in analysis.untouchedSubjects:
                reason = f"Explore a new {subj} subject track matched to {profile.gradeLevel}."
            else:
                reason = f"Matches your {profile.gradeLevel} track and {style_label} learning style."

        results.append(
            RecommendationCandidate(
                recommendationId=f"course-{cid_int}",
                itemType="COURSE",
                actionType=action,  # type: ignore[arg-type]
                title=title,
                description=str(c.get("description") or f"{subj} • {c_grade}").strip(),
                subject=subj,
                gradeLevel=c_grade,  # type: ignore[arg-type]
                difficulty=mapped_diff,  # type: ignore[arg-type]
                courseId=cid_int,
                courseTitle=title,
                icon=SUBJECT_ICON_MAP.get(subj, "twemoji:books"),
                targetPath=target_path,
                navigationState=nav_state,
                reason=reason,
                tags=[subj, c_grade, "Enrolled" if is_enrolled else "Discover"],
            )
        )

    if not results:
        starter_courses = [
            ("Mathematics", f"{profile.gradeLevel} Numbers & Fractions Quest", "Build rock-solid arithmetic and fraction skills."),
            ("ICT", f"{profile.gradeLevel} Digital Explorer", "Learn computer fundamentals and safe digital tools."),
            ("Environmental Studies", f"{profile.gradeLevel} Ocean & Nature Lab", "Discover ecosystems, habitats, and conservation."),
        ]
        for idx, (subj, title, desc) in enumerate(starter_courses, start=1):
            results.append(
                RecommendationCandidate(
                    recommendationId=f"starter-course-{idx}",
                    itemType="COURSE",
                    actionType="ENROLL",
                    title=title,
                    description=desc,
                    subject=subj,
                    gradeLevel=profile.gradeLevel,
                    difficulty=analysis.recommendedDifficulty,
                    icon=SUBJECT_ICON_MAP.get(subj, "twemoji:books"),
                    targetPath="/courses",
                    navigationState={"category": subj},
                    reason=f"Core {profile.gradeLevel} subject course recommended for your {style_label} style.",
                    tags=[subj, profile.gradeLevel, "Starter Track"],
                )
            )

    return results


def _generate_map_activity_candidates(
    activities_by_module: Dict[int, List[Dict[str, Any]]],
    module_map: Dict[int, Dict[str, Any]],
    course_map: Dict[int, Dict[str, Any]],
    subject_name_by_id: Dict[Any, str],
    profile: StudentLearningProfile,
    analysis: LearningProfileAnalysis,
) -> List[RecommendationCandidate]:
    results: List[RecommendationCandidate] = []
    completed_set = set(profile.completedActivityIds)
    low_score_set = set(profile.lowScoreActivityIds)

    for mid, acts in activities_by_module.items():
        mod = module_map.get(mid, {})
        cid = int(mod["courseId"]) if mod.get("courseId") else None
        course = course_map.get(cid, {}) if cid else {}
        subj = (
            _course_subject(course, subject_name_by_id)
            if course
            else normalize_subject_name(mod.get("title") or acts[0].get("title"))
        )
        mod_title = str(mod.get("title") or f"Module {mid}")
        c_title = str(course.get("title") or "")

        retry_acts = [a for a in acts if int(a.get("activityId") or 0) in low_score_set]
        next_uncompleted = [a for a in acts if int(a.get("activityId") or 0) not in completed_set]

        chosen: List[Dict[str, Any]] = []
        seen_aids = set()
        for candidate_act in retry_acts[:1] + next_uncompleted[:1]:
            aid = int(candidate_act.get("activityId") or 0)
            if aid and aid not in seen_aids:
                seen_aids.add(aid)
                chosen.append(candidate_act)

        for act in chosen:
            aid = int(act["activityId"])
            is_retry = aid in low_score_set
            prev_best = profile.bestScoreByActivityId.get(str(aid))
            act_grade, _ = normalize_grade(
                act.get("gradeLevel") or course.get("gradeLevel") or profile.gradeLevel
            )
            act_diff = str(act.get("difficulty") or analysis.recommendedDifficulty).upper()
            if act_diff not in {"EASY", "MEDIUM", "HARD"}:
                act_diff = analysis.recommendedDifficulty
            qtype = str(act.get("activityType") or "MCQ").upper()
            qlabel = QTYPE_LABEL_MAP.get(qtype, qtype.replace("_", " ").title())

            if is_retry and prev_best is not None:
                if prev_best >= 40:
                    reason = (
                        f"You previously scored {round(prev_best)}% — score 60%+ on a retry "
                        "to earn extra stars & Silver/Gold batches!"
                    )
                else:
                    reason = (
                        f"Score 40%+ on this retry to pass Level {act.get('displayOrder') or 1} "
                        "and unlock the next map quest!"
                    )
            else:
                reason = (
                    f"Next Content Creator quest in {mod_title} ({qlabel}) — "
                    "complete it to advance on your Activity Map!"
                )

            results.append(
                RecommendationCandidate(
                    recommendationId=f"map-activity-{aid}",
                    itemType="ACTIVITY",
                    actionType="RETRY_MAP" if is_retry else "PLAY_MAP",
                    title=str(act.get("title") or f"{mod_title} Quest"),
                    description=f"{subj} • {qlabel} • {act_diff.title()} Difficulty",
                    subject=subj,
                    gradeLevel=act_grade,
                    difficulty=act_diff,  # type: ignore[arg-type]
                    activityType=qtype,
                    courseId=cid,
                    moduleId=mid,
                    activityId=aid,
                    courseTitle=c_title or None,
                    moduleTitle=mod_title,
                    icon=SUBJECT_ICON_MAP.get(subj, "twemoji:world-map"),
                    targetPath="/activity-map",
                    navigationState={
                        "moduleId": mid,
                        "module": mod_title,
                        "courseId": cid,
                        "course": c_title,
                        "subject": subj,
                    },
                    reason=reason,
                    tags=[subj, "Activity Map", qlabel],
                )
            )

    return results


def _generate_ai_practice_candidates(
    courses: List[Dict[str, Any]],
    modules_by_course: Dict[int, List[Dict[str, Any]]],
    subject_name_by_id: Dict[Any, str],
    profile: StudentLearningProfile,
    analysis: LearningProfileAnalysis,
) -> List[RecommendationCandidate]:
    results: List[RecommendationCandidate] = []
    practice_subjects = (
        list(analysis.weakSubjects)
        or list(analysis.untouchedSubjects[:2])
        or list(CORE_SUBJECTS)
    )
    style_label = profile.learningStyle.lower().replace("_", " ")
    qtypes = analysis.preferredQuestionTypes or ["MCQ"]

    for idx, subj in enumerate(practice_subjects[:3]):
        qtype = qtypes[idx % len(qtypes)]
        qlabel = QTYPE_LABEL_MAP.get(qtype, qtype)
        matched_mod: Optional[Dict[str, Any]] = None
        matched_course: Optional[Dict[str, Any]] = None

        for c in courses:
            if _course_subject(c, subject_name_by_id) == subj:
                cid = int(c.get("courseId") or c.get("id"))
                c_mods = modules_by_course.get(cid, [])
                if c_mods:
                    matched_mod = c_mods[0]
                    matched_course = c
                    break

        mod_id = int(matched_mod["moduleId"]) if matched_mod and matched_mod.get("moduleId") else None
        mod_title = str(matched_mod.get("title")) if matched_mod else f"{subj} Essentials"
        course_id = (
            int(matched_course["courseId"])
            if matched_course and matched_course.get("courseId")
            else None
        )
        course_title = (
            str(matched_course.get("title"))
            if matched_course
            else f"{subj} ({profile.gradeLevel})"
        )

        is_weak = subj in analysis.weakSubjects
        reason = (
            f"Targeted {qlabel} practice at {analysis.recommendedDifficulty.title()} difficulty "
            f"to strengthen {subj} before retrying the Activity Map."
            if is_weak
            else f"Custom {qlabel} warm-up tailored to your {style_label} learning style."
        )

        results.append(
            RecommendationCandidate(
                recommendationId=f"ai-practice-{subj.lower().replace(' ', '-')}-{qtype.lower()}",
                itemType="AI_PRACTICE",
                actionType="GENERATE_PRACTICE",
                title=f"{mod_title}: {qlabel} Boost",
                description=f"AI Practice • {subj} • {analysis.recommendedDifficulty.title()} Difficulty",
                subject=subj,
                gradeLevel=profile.gradeLevel,
                difficulty=analysis.recommendedDifficulty,
                activityType=qtype,
                courseId=course_id,
                moduleId=mod_id,
                courseTitle=course_title,
                moduleTitle=mod_title,
                icon=SUBJECT_ICON_MAP.get(subj, "twemoji:sparkles"),
                targetPath="/generate-activity",
                navigationState={
                    "subject": subj,
                    "course": course_title,
                    "courseId": course_id,
                    "module": mod_title,
                    "moduleId": mod_id,
                    "preselectType": qlabel,
                },
                reason=reason,
                tags=[subj, "AI Practice", qlabel],
            )
        )

    return results


def _generate_study_and_badge_candidates(
    profile: StudentLearningProfile,
    analysis: LearningProfileAnalysis,
) -> List[RecommendationCandidate]:
    results: List[RecommendationCandidate] = []
    if analysis.weakSubjects:
        weak_s = analysis.weakSubjects[0]
        stat = profile.subjectStats.get(weak_s)
        results.append(
            RecommendationCandidate(
                recommendationId=f"study-tip-review-{weak_s.lower().replace(' ', '-')}",
                itemType="STUDY_TIP",
                actionType="REVIEW_NOTES",
                title=f"Review {weak_s} Lesson Slides",
                description=(
                    f"Your average in {weak_s} is {stat.averageScore if stat else 0}%. "
                    "Reviewing visual notes first boosts retention!"
                ),
                subject=weak_s,
                gradeLevel=profile.gradeLevel,
                difficulty="EASY",
                icon="twemoji:open-book",
                targetPath="/courses",
                navigationState={"category": weak_s},
                reason=f"Recommended before your next {weak_s} Activity Map attempt.",
                tags=["Study Tip", weak_s],
            )
        )

    if analysis.badgeOpportunities:
        top_badge = analysis.badgeOpportunities[0]
        results.append(
            RecommendationCandidate(
                recommendationId=f"badge-quest-{top_badge.badgeId}",
                itemType="STUDY_TIP",
                actionType="EARN_BADGE",
                title=f"Unlock Batch: {top_badge.badgeName}",
                description=f"{top_badge.requirement} ({top_badge.progressText})",
                subject="General",
                gradeLevel=profile.gradeLevel,
                difficulty=analysis.recommendedDifficulty,
                icon=top_badge.icon,
                targetPath="/progress",
                navigationState={},
                reason=f"Closest permanent batch unlock — {top_badge.progressText}!",
                tags=["Badge Quest", top_badge.badgeName],
            )
        )

    return results


class RecommendationGenerator:
    """Generates candidate Courses, Activity Map Quests, AI Practice, and Study/Badge Tips."""

    def __init__(
        self,
        enable_llm: Optional[bool] = None,
        gemini_client_factory: Optional[Callable[[str], Any]] = None,
        openai_client_factory: Optional[Callable[[str, float], Any]] = None,
    ) -> None:
        self.enable_llm = settings.enable_llm if enable_llm is None else enable_llm
        self.gemini_client_factory = gemini_client_factory
        self.openai_client_factory = openai_client_factory

    def generate(
        self,
        data: CollectedStudentData,
        profile: StudentLearningProfile,
        analysis: LearningProfileAnalysis,
    ) -> Tuple[List[RecommendationCandidate], str]:
        (
            subject_name_by_id,
            courses,
            course_map,
            module_map,
            modules_by_course,
            activities_by_module,
        ) = _index_catalog(data)

        candidates: List[RecommendationCandidate] = []
        candidates.extend(
            _generate_course_candidates(courses, subject_name_by_id, profile, analysis)
        )
        candidates.extend(
            _generate_map_activity_candidates(
                activities_by_module,
                module_map,
                course_map,
                subject_name_by_id,
                profile,
                analysis,
            )
        )
        candidates.extend(
            _generate_ai_practice_candidates(
                courses,
                modules_by_course,
                subject_name_by_id,
                profile,
                analysis,
            )
        )
        candidates.extend(_generate_study_and_badge_candidates(profile, analysis))

        mascot_tip = self._build_mascot_tip(profile, analysis, candidates)
        return candidates, mascot_tip

    def _build_mascot_tip(
        self,
        profile: StudentLearningProfile,
        analysis: LearningProfileAnalysis,
        candidates: List[RecommendationCandidate],
    ) -> str:
        fallback = analysis.insightHeadline or (
            f"Keep exploring {profile.gradeLevel} quests tailored to your learning style!"
        )
        if not self.enable_llm:
            return fallback

        api_gemini = settings.gemini_api_key
        api_openai = settings.openai_api_key
        if not api_gemini and not api_openai:
            return fallback

        summary_ctx = {
            "name": profile.studentName,
            "grade": profile.gradeLevel,
            "learningStyle": profile.learningStyle,
            "difficulty": analysis.recommendedDifficulty,
            "avgScore": profile.averageScore,
            "stars": profile.starsEarned,
            "weakSubjects": analysis.weakSubjects,
            "strongSubjects": analysis.strongSubjects,
            "nextBadge": analysis.badgeOpportunities[0].badgeName if analysis.badgeOpportunities else None,
            "topTitles": [c.title for c in candidates[:3]],
        }
        prompt = (
            "You are Bubbles, an encouraging dolphin mascot in an educational app for primary school children (Grades 3-5). "
            "Write ONE cheerful, personalized 1-2 sentence study tip (max 35 words) based strictly on this student profile: "
            f"{json.dumps(summary_ctx)}. Return plain text only without quotes or markdown."
        )

        if api_gemini:
            try:
                if self.gemini_client_factory is not None:
                    client = self.gemini_client_factory(api_gemini)
                else:
                    from google import genai

                    client = genai.Client(api_key=api_gemini)
                resp = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
                if resp and getattr(resp, "text", None) and resp.text.strip():
                    return resp.text.strip().strip('"')
            except Exception as exc:
                log.debug("Gemini mascot tip skipped (fallback used): %s", exc)

        if api_openai:
            try:
                if self.openai_client_factory is not None:
                    oa = self.openai_client_factory(api_openai, settings.llm_timeout_seconds)
                else:
                    from openai import OpenAI

                    oa = OpenAI(api_key=api_openai, timeout=settings.llm_timeout_seconds)
                resp = oa.chat.completions.create(
                    model="gpt-4.1-mini",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.5,
                    max_tokens=90,
                )
                msg = resp.choices[0].message.content
                if msg and msg.strip():
                    return msg.strip().strip('"')
            except Exception as exc:
                log.debug("OpenAI mascot tip skipped (fallback used): %s", exc)

        return fallback
