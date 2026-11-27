"""Stage 2: Student Learning Profile Builder from Collected Microservice Data."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from models import (
    CollectedStudentData,
    StudentLearningProfile,
    SubjectLearningStat,
)

CORE_SUBJECTS = ("Mathematics", "ICT", "Environmental Studies")


def normalize_subject_name(raw: Optional[str]) -> str:
    text = str(raw or "").strip().lower()
    if not text:
        return "General"
    if "math" in text:
        return "Mathematics"
    if "ict" in text or "comput" in text or "digital" in text or "cyber" in text:
        return "ICT"
    if "env" in text or "science" in text or "eco" in text or "nature" in text:
        return "Environmental Studies"
    if "english" in text:
        return "English"
    return str(raw).strip().title()


def normalize_grade(raw: Optional[str]) -> Tuple[str, str]:
    text = str(raw or "").strip()
    match = re.search(r"(\d+)", text)
    if match:
        num = int(match.group(1))
        if num in (3, 4, 5):
            return f"Grade {num}", f"GRADE_{num}"
    return "Grade 4", "GRADE_4"


def normalize_learning_style(raw: Optional[str]) -> str:
    text = str(raw or "").strip().upper().replace("-", "_").replace(" ", "_")
    mapping = {
        "VISUAL": "VISUAL",
        "INTERACTIVE": "INTERACTIVE",
        "KINESTHETIC": "INTERACTIVE",
        "HANDS_ON": "INTERACTIVE",
        "STEP_BY_STEP": "STEP_BY_STEP",
        "READING": "STEP_BY_STEP",
        "NOTES": "STEP_BY_STEP",
        "PRACTICE_FIRST": "PRACTICE_FIRST",
        "ANALYTICAL": "ANALYTICAL",
        "PROBLEM_SOLVING": "ANALYTICAL",
    }
    return mapping.get(text, "INTERACTIVE")


def normalize_difficulty(raw: Optional[str]) -> str:
    text = str(raw or "").strip().upper()
    if text in {"EASY", "BEGINNER"}:
        return "EASY"
    if text in {"MEDIUM", "INTERMEDIATE"}:
        return "MEDIUM"
    if text in {"HARD", "ADVANCED"}:
        return "HARD"
    return "ADAPTIVE"


def _extract_enrollment_ids(
    enrollments: List[Dict[str, Any]],
) -> Tuple[List[int], List[int], List[int]]:
    enrolled_ids: List[int] = []
    completed_ids: List[int] = []
    pending_ids: List[int] = []

    for e in enrollments:
        if not isinstance(e, dict) or not e.get("courseId"):
            continue
        c_id = int(e["courseId"])
        status = str(e.get("status") or "PENDING").upper()
        if status in {"ACTIVE", "ACCEPTED", "APPROVED"}:
            if c_id not in enrolled_ids:
                enrolled_ids.append(c_id)
        elif status == "COMPLETED":
            if c_id not in completed_ids:
                completed_ids.append(c_id)
            if c_id not in enrolled_ids:
                enrolled_ids.append(c_id)
        elif status == "PENDING" and c_id not in pending_ids:
            pending_ids.append(c_id)

    return enrolled_ids, completed_ids, pending_ids


def _extract_badge_lists(badges_raw: List[Dict[str, Any]]) -> Tuple[List[str], List[str]]:
    earned: List[str] = []
    locked: List[str] = []
    for b in badges_raw:
        if not isinstance(b, dict):
            continue
        bid = b.get("id") or b.get("badgeCode")
        if not bid:
            continue
        if b.get("earned"):
            earned.append(str(bid))
        else:
            locked.append(str(bid))
    return earned, locked


def _parse_int_activity_id(raw_key: Any) -> Optional[int]:
    if raw_key is None:
        return None
    try:
        return int(str(raw_key).split("-")[-1])
    except ValueError:
        return None


def _compute_subject_trend(
    attempts: List[Dict[str, Any]],
    avg_score: float,
    mastery: float,
) -> str:
    attempt_count = len(attempts)
    if attempt_count == 0 and mastery == 0.0:
        return "NOT_STARTED"
    if attempt_count >= 2:
        newest = attempts[0]["pct"]
        oldest = attempts[-1]["pct"]
        if newest >= oldest + 5:
            return "IMPROVING"
        if newest <= oldest - 10 and newest < 70.0:
            return "NEEDS_ATTENTION"
    if (attempt_count > 0 and avg_score < 60.0) or (
        mastery > 0 and mastery < 35.0 and attempt_count > 0
    ):
        return "NEEDS_ATTENTION"
    return "STEADY"


def _build_subject_stats(
    subject_buckets: Dict[str, List[Dict[str, Any]]],
    mastery_by_subject: Dict[str, float],
) -> Dict[str, SubjectLearningStat]:
    all_names = set(subject_buckets.keys()) | set(mastery_by_subject.keys())
    stats: Dict[str, SubjectLearningStat] = {}

    for s_name in sorted(all_names):
        attempts = subject_buckets.get(s_name, [])
        mastery = round(mastery_by_subject.get(s_name, 0.0), 1)
        attempt_count = len(attempts)
        passed_count = sum(1 for a in attempts if a["passed"])
        avg_s = round(sum(a["pct"] for a in attempts) / attempt_count, 1) if attempt_count else 0.0
        last_s = round(attempts[0]["pct"], 1) if attempt_count else None
        total_mins = sum(a["time"] for a in attempts)
        trend = _compute_subject_trend(attempts, avg_s, mastery)

        stats[s_name] = SubjectLearningStat(
            subject=s_name,
            masteryPercentage=mastery,
            attemptCount=attempt_count,
            passedCount=passed_count,
            averageScore=avg_s,
            lastScore=last_s,
            totalTimeSpentMins=total_mins,
            trend=trend,  # type: ignore[arg-type]
        )

    return stats


class StudentLearningProfileBuilder:
    """Transforms collected multi-service payloads into a unified StudentLearningProfile."""

    def build(self, data: CollectedStudentData) -> StudentLearningProfile:
        ctx = data.clientContext
        user = data.userProfile or {}
        prefs = data.preferences or {}
        summary = data.progressSummary or {}

        # 1. Identity & Grade Level
        full_name = (
            " ".join(filter(None, [user.get("firstName"), user.get("lastName")])).strip()
            or user.get("username")
            or (ctx.studentName if ctx and ctx.studentName else None)
            or "Explorer"
        )
        raw_grade = (
            (ctx.gradeLevel if ctx and ctx.gradeLevel else None)
            or next(
                (
                    e.get("studentGrade") or e.get("gradeLevel")
                    for e in data.enrollments
                    if isinstance(e, dict) and (e.get("studentGrade") or e.get("gradeLevel"))
                ),
                None,
            )
            or "Grade 4"
        )
        grade_display, grade_enum = normalize_grade(raw_grade)

        # 2. Student Settings / Learning Preferences
        learning_style = normalize_learning_style(
            prefs.get("learningStyle") or (ctx.learningStyle if ctx else None)
        )
        difficulty_pref = normalize_difficulty(
            prefs.get("difficultyLevel") or (ctx.difficultyLevel if ctx else None)
        )

        # 3. Enrollments breakdown
        enrolled_ids, completed_course_ids, pending_ids = _extract_enrollment_ids(data.enrollments)

        # 4. Lookup tables for linking progress records to subjects and question types
        course_by_id = {
            int(c.get("courseId") or c.get("id")): c
            for c in data.courses
            if isinstance(c, dict) and (c.get("courseId") or c.get("id"))
        }
        module_by_id = {
            int(m.get("moduleId") or m.get("id")): m
            for m in data.modules
            if isinstance(m, dict) and (m.get("moduleId") or m.get("id"))
        }
        activity_by_id = {
            int(a.get("activityId") or a.get("id")): a
            for a in data.activities
            if isinstance(a, dict) and (a.get("activityId") or a.get("id"))
        }

        subject_buckets: Dict[str, List[Dict[str, Any]]] = {s: [] for s in CORE_SUBJECTS}
        qtype_buckets: Dict[str, List[float]] = {}
        best_scores: Dict[str, float] = {}

        def _ingest_attempt(
            subject: str,
            pct: float,
            passed: bool,
            time_mins: int,
            act_id: Optional[int],
            qtype: Optional[str],
        ) -> None:
            norm_subj = normalize_subject_name(subject)
            subject_buckets.setdefault(norm_subj, []).append(
                {"pct": pct, "passed": passed, "time": time_mins}
            )
            if qtype:
                qtype_buckets.setdefault(str(qtype).upper(), []).append(pct)
            if act_id:
                key = str(act_id)
                best_scores[key] = max(best_scores.get(key, 0.0), pct)

        for rec in data.progressHistory:
            if not isinstance(rec, dict):
                continue
            act_id = _parse_int_activity_id(rec.get("activityId"))
            act_meta = activity_by_id.get(act_id) if act_id else None
            subj = rec.get("subjectName")
            if not subj and rec.get("moduleId") in module_by_id:
                c_id = module_by_id[rec["moduleId"]].get("courseId")
                if c_id in course_by_id:
                    subj = course_by_id[c_id].get("subject") or course_by_id[c_id].get("title")
            pct = float(rec.get("scorePercentage") or 0.0)
            passed = bool(rec.get("isPassed")) if rec.get("isPassed") is not None else pct >= 40.0
            _ingest_attempt(
                subject=subj or "General",
                pct=pct,
                passed=passed,
                time_mins=int(rec.get("timeSpentMins") or 2),
                act_id=act_id,
                qtype=(act_meta or {}).get("activityType"),
            )

        if ctx:
            if isinstance(ctx.completedMapActivities, dict):
                for key, rec in ctx.completedMapActivities.items():
                    if not isinstance(rec, dict):
                        continue
                    act_id_num = _parse_int_activity_id(rec.get("activityId") or key)
                    pct = float(rec.get("percentage") or 0.0)
                    passed = bool(rec.get("passed")) if "passed" in rec else pct >= 40.0
                    subj = rec.get("subject") or "General"
                    qtype = (
                        (activity_by_id.get(act_id_num) or {}).get("activityType")
                        if act_id_num
                        else None
                    )
                    if not data.progressHistory or (
                        act_id_num and str(act_id_num) not in best_scores
                    ):
                        _ingest_attempt(subj, pct, passed, 2, act_id_num, qtype)
                    elif act_id_num:
                        best_scores[str(act_id_num)] = max(
                            best_scores.get(str(act_id_num), 0.0), pct
                        )

            if isinstance(ctx.recentScores, list) and not data.progressHistory:
                for sc in ctx.recentScores:
                    if not isinstance(sc, dict):
                        continue
                    sc_aid = _parse_int_activity_id(sc.get("activityId"))
                    if sc_aid and str(sc_aid) in best_scores:
                        continue
                    pct = float(sc.get("percentage") or 0.0)
                    _ingest_attempt(
                        subject=sc.get("subject") or sc.get("courseTitle") or "General",
                        pct=pct,
                        passed=bool(sc.get("passed")) if "passed" in sc else pct >= 40.0,
                        time_mins=2,
                        act_id=sc_aid,
                        qtype=sc.get("activityType"),
                    )

        completed_act_ids: List[int] = []
        low_score_act_ids: List[int] = []
        for aid_str, best in best_scores.items():
            aid = _parse_int_activity_id(aid_str)
            if aid is None:
                continue
            if best >= 40.0:
                completed_act_ids.append(aid)
            if best < 60.0:
                low_score_act_ids.append(aid)

        # 5. Subject stats & mastery percentages
        raw_subj_prog = summary.get("subjectProgress") or (ctx.subjectProgress if ctx else None) or {}
        mastery_by_subject: Dict[str, float] = {}
        if isinstance(raw_subj_prog, dict):
            for s_name, detail in raw_subj_prog.items():
                norm_s = normalize_subject_name(s_name)
                pct_val = (
                    float(detail.get("percentage") or 0.0)
                    if isinstance(detail, dict)
                    else float(detail or 0.0)
                )
                mastery_by_subject[norm_s] = max(mastery_by_subject.get(norm_s, 0.0), pct_val)

        if ctx and ctx.preferredSubjects:
            for ps in ctx.preferredSubjects:
                subject_buckets.setdefault(normalize_subject_name(ps), [])

        subject_stats = _build_subject_stats(subject_buckets, mastery_by_subject)

        qtype_stats: Dict[str, Dict[str, Any]] = {
            qtype: {
                "attempts": len(scores),
                "averageScore": round(sum(scores) / len(scores), 1),
            }
            for qtype, scores in qtype_buckets.items()
        }

        # 6. Badges & summary metrics
        badges_raw = summary.get("badges") or (ctx.badges if ctx else None) or []
        earned_badges, locked_badges = _extract_badge_lists(badges_raw)

        stars_earned = int(
            summary.get("starsEarned")
            if summary.get("starsEarned") is not None
            else (ctx.starsEarned if ctx and ctx.starsEarned is not None else 0)
        )
        map_done = int(
            summary.get("mapActivitiesDone")
            if summary.get("mapActivitiesDone") is not None
            else (
                ctx.mapActivitiesDone
                if ctx and ctx.mapActivitiesDone is not None
                else len(completed_act_ids)
            )
        )
        practice_done = int(
            summary.get("practiceActivitiesDone")
            if summary.get("practiceActivitiesDone") is not None
            else (ctx.practiceActivitiesDone if ctx and ctx.practiceActivitiesDone is not None else 0)
        )
        streak_days = int(
            summary.get("currentStreakDays")
            if summary.get("currentStreakDays") is not None
            else (ctx.currentStreakDays if ctx and ctx.currentStreakDays is not None else 1)
        )

        raw_avg = summary.get("averageScore")
        if raw_avg is None or float(raw_avg) == 0.0:
            if ctx and ctx.averageScore:
                raw_avg = ctx.averageScore
            elif ctx and ctx.lastScorePercentage is not None:
                raw_avg = ctx.lastScorePercentage
            else:
                all_scores = [a["pct"] for arr in subject_buckets.values() for a in arr]
                raw_avg = round(sum(all_scores) / len(all_scores), 1) if all_scores else 0.0

        return StudentLearningProfile(
            userId=data.userId,
            studentName=full_name,
            gradeLevel=grade_display,
            gradeEnum=grade_enum,
            learningStyle=learning_style,
            difficultyPreference=difficulty_pref,
            enrolledCourseIds=enrolled_ids,
            completedCourseIds=completed_course_ids,
            pendingCourseIds=pending_ids,
            starsEarned=stars_earned,
            averageScore=round(float(raw_avg or 0.0), 1),
            mapActivitiesDone=map_done,
            practiceActivitiesDone=practice_done,
            currentStreakDays=streak_days,
            subjectStats=subject_stats,
            questionTypeStats=qtype_stats,
            earnedBadges=earned_badges,
            lockedBadges=locked_badges,
            completedActivityIds=sorted(completed_act_ids),
            lowScoreActivityIds=sorted(low_score_act_ids),
            bestScoreByActivityId=best_scores,
        )
