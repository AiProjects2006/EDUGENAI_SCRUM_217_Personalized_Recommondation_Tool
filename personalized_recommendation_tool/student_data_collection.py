"""Stage 1: Student Data Collection from the 6 Existing Microservices."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple
import httpx

from personalized_recommendation_tool.config import settings
from personalized_recommendation_tool.models import ClientContextPayload, CollectedStudentData

log = logging.getLogger(__name__)


def _unwrap_data(payload: Any, default: Any) -> Any:
    """Extract `.data` from standard Java ApiResponse wrappers, or return raw JSON."""
    if payload is None:
        return default
    if isinstance(payload, dict) and "data" in payload and (
        "success" in payload or "message" in payload
    ):
        val = payload.get("data")
        return default if val is None else val
    return payload


def is_creator_published_activity(act: Dict[str, Any]) -> bool:
    """Keep only Content Creator published activities for the Student Activity Map."""
    if not isinstance(act, dict):
        return False
    status = str(act.get("status") or "PUBLISHED").upper()
    if status != "PUBLISHED":
        return False
    role = str(act.get("createdByRole") or "").upper()
    if role == "STUDENT":
        return False
    desc = str(act.get("description") or "")
    if not role and desc.startswith("AI-generated "):
        return False
    return True


async def _fetch_json(
    client: httpx.AsyncClient,
    url: str,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[str, Any]:
    try:
        resp = await client.get(url, headers=headers or {})
        if resp.status_code == 404:
            return "not_found", None
        if resp.status_code >= 400:
            return f"http_{resp.status_code}", None
        return "ok", resp.json()
    except Exception as exc:
        log.debug("Microservice fetch error for %s: %s", url, exc)
        return "unreachable", None


def _enrich_course_subjects(
    courses: List[Dict[str, Any]],
    subjects: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    subject_map: Dict[Any, str] = {
        s.get("subjectId"): s.get("name")
        for s in subjects
        if isinstance(s, dict) and s.get("subjectId") and s.get("name")
    }
    enriched: List[Dict[str, Any]] = []
    for c in courses:
        if not isinstance(c, dict):
            continue
        item = dict(c)
        if not item.get("subject") and item.get("subjectId") in subject_map:
            item["subject"] = subject_map[item["subjectId"]]
        enriched.append(item)
    return enriched


def _apply_client_fallback(
    user_id: int,
    user_profile: Dict[str, Any],
    preferences: Dict[str, Any],
    enrollments: List[Dict[str, Any]],
    courses: List[Dict[str, Any]],
    modules: List[Dict[str, Any]],
    activities: List[Dict[str, Any]],
    progress_summary: Dict[str, Any],
    source_health: Dict[str, str],
    client_context: Optional[ClientContextPayload],
) -> Tuple[
    Dict[str, Any],
    Dict[str, Any],
    List[Dict[str, Any]],
    List[Dict[str, Any]],
    List[Dict[str, Any]],
    List[Dict[str, Any]],
    Dict[str, Any],
    Dict[str, str],
]:
    if not client_context:
        return (
            user_profile,
            preferences,
            enrollments,
            courses,
            modules,
            activities,
            progress_summary,
            source_health,
        )

    if not user_profile and (client_context.studentName or client_context.email):
        parts = str(client_context.studentName or "").strip().split(None, 1)
        user_profile = {
            "id": user_id,
            "firstName": parts[0] if parts else "Explorer",
            "lastName": parts[1] if len(parts) > 1 else "",
            "email": client_context.email,
        }
        if source_health["userService"] != "ok":
            source_health["userService"] = "client_fallback"

    if not preferences and (client_context.learningStyle or client_context.difficultyLevel):
        preferences = {
            "userId": user_id,
            "learningStyle": client_context.learningStyle or "INTERACTIVE",
            "difficultyLevel": client_context.difficultyLevel or "ADAPTIVE",
        }
        if source_health["studentSettingsService"] != "ok":
            source_health["studentSettingsService"] = "client_fallback"

    if client_context.enrollments and not enrollments:
        enrollments = list(client_context.enrollments)
        if source_health["enrollmentService"] != "ok":
            source_health["enrollmentService"] = "client_fallback"

    if client_context.courses and not courses:
        courses = list(client_context.courses)
        if source_health["courseService"] != "ok":
            source_health["courseService"] = "client_fallback"

    if client_context.modules and not modules:
        modules = list(client_context.modules)
        if source_health["courseService"] != "ok":
            source_health["courseService"] = "client_fallback"

    if client_context.activities and not activities:
        activities = [
            a for a in client_context.activities if is_creator_published_activity(a)
        ]
        if source_health["activityService"] != "ok":
            source_health["activityService"] = "client_fallback"

    if not progress_summary and (
        client_context.subjectProgress is not None
        or client_context.starsEarned is not None
        or client_context.averageScore is not None
    ):
        progress_summary = {
            "userId": user_id,
            "starsEarned": client_context.starsEarned or 0,
            "averageScore": client_context.averageScore or 0,
            "mapActivitiesDone": client_context.mapActivitiesDone or 0,
            "practiceActivitiesDone": client_context.practiceActivitiesDone or 0,
            "currentStreakDays": client_context.currentStreakDays or 1,
            "subjectProgress": client_context.subjectProgress or {},
            "badges": client_context.badges or [],
        }
        if source_health["progressTrackingService"] != "ok":
            source_health["progressTrackingService"] = "client_fallback"

    return (
        user_profile,
        preferences,
        enrollments,
        courses,
        modules,
        activities,
        progress_summary,
        source_health,
    )


class StudentDataCollector:
    """Collects student, course, activity, enrollment, settings, and progress data."""

    def __init__(
        self,
        user_service_url: str = settings.user_service_url,
        course_service_url: str = settings.course_service_url,
        activity_service_url: str = settings.activity_service_url,
        enrollment_service_url: str = settings.enrollment_service_url,
        settings_service_url: str = settings.settings_service_url,
        progress_service_url: str = settings.progress_service_url,
        timeout_seconds: float = settings.http_timeout_seconds,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self.user_service_url = user_service_url.rstrip("/")
        self.course_service_url = course_service_url.rstrip("/")
        self.activity_service_url = activity_service_url.rstrip("/")
        self.enrollment_service_url = enrollment_service_url.rstrip("/")
        self.settings_service_url = settings_service_url.rstrip("/")
        self.progress_service_url = progress_service_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def assemble(
        self,
        user_id: int,
        raw_results: List[Tuple[str, Any]],
        client_context: Optional[ClientContextPayload] = None,
    ) -> CollectedStudentData:
        """Normalize fetched payloads, filter creator activities, and merge client fallback."""
        (
            (user_status, user_raw),
            (pref_status, pref_raw),
            (enroll_status, enroll_raw),
            (subj_status, subj_raw),
            (course_status, course_raw),
            (mod_status, mod_raw),
            (act_status, act_raw),
            (prog_sum_status, prog_sum_raw),
            (prog_hist_status, prog_hist_raw),
        ) = raw_results

        user_profile = _unwrap_data(user_raw, {})
        if not isinstance(user_profile, dict):
            user_profile = {}

        preferences = _unwrap_data(pref_raw, {})
        if not isinstance(preferences, dict):
            preferences = {}

        enrollments = _unwrap_data(enroll_raw, [])
        if not isinstance(enrollments, list):
            enrollments = []

        subjects = _unwrap_data(subj_raw, [])
        if not isinstance(subjects, list):
            subjects = []

        courses = _unwrap_data(course_raw, [])
        if not isinstance(courses, list):
            courses = []

        modules = _unwrap_data(mod_raw, [])
        if not isinstance(modules, list):
            modules = []

        activities_raw = _unwrap_data(act_raw, [])
        if not isinstance(activities_raw, list):
            activities_raw = []
        activities = [a for a in activities_raw if is_creator_published_activity(a)]

        progress_summary = _unwrap_data(prog_sum_raw, {})
        if not isinstance(progress_summary, dict):
            progress_summary = {}

        progress_history = _unwrap_data(prog_hist_raw, [])
        if not isinstance(progress_history, list):
            progress_history = []

        enriched_courses = _enrich_course_subjects(courses, subjects)
        source_health: Dict[str, str] = {
            "userService": user_status,
            "studentSettingsService": pref_status,
            "enrollmentService": enroll_status,
            "courseService": "ok" if "ok" in {subj_status, course_status, mod_status} else course_status,
            "activityService": act_status,
            "progressTrackingService": (
                "ok" if "ok" in {prog_sum_status, prog_hist_status} else prog_sum_status
            ),
        }

        (
            user_profile,
            preferences,
            enrollments,
            enriched_courses,
            modules,
            activities,
            progress_summary,
            source_health,
        ) = _apply_client_fallback(
            user_id=user_id,
            user_profile=user_profile,
            preferences=preferences,
            enrollments=enrollments,
            courses=enriched_courses,
            modules=modules,
            activities=activities,
            progress_summary=progress_summary,
            source_health=source_health,
            client_context=client_context,
        )

        return CollectedStudentData(
            userId=user_id,
            userProfile=user_profile,
            preferences=preferences,
            enrollments=enrollments,
            subjects=subjects,
            courses=enriched_courses,
            modules=modules,
            activities=activities,
            progressSummary=progress_summary,
            progressHistory=progress_history,
            clientContext=client_context,
            sourceHealth=source_health,
        )

    async def collect(
        self,
        user_id: int,
        client_context: Optional[ClientContextPayload] = None,
        auth_header: Optional[str] = None,
    ) -> CollectedStudentData:
        """Concurrently fetch data from all 6 microservices for the given student."""
        headers: Dict[str, str] = {"Accept": "application/json"}
        if auth_header:
            headers["Authorization"] = auth_header

        client_kwargs: Dict[str, Any] = {"timeout": httpx.Timeout(self.timeout_seconds)}
        if self.transport is not None:
            client_kwargs["transport"] = self.transport

        async with httpx.AsyncClient(**client_kwargs) as client:
            raw_results = await asyncio.gather(
                _fetch_json(client, f"{self.user_service_url}/api/users/{user_id}", headers),
                _fetch_json(
                    client,
                    f"{self.settings_service_url}/api/v1/preferences/user/{user_id}",
                    headers,
                ),
                _fetch_json(
                    client,
                    f"{self.enrollment_service_url}/api/v1/enrollments/user/{user_id}",
                    headers,
                ),
                _fetch_json(client, f"{self.course_service_url}/api/v1/subjects", headers),
                _fetch_json(client, f"{self.course_service_url}/api/v1/courses", headers),
                _fetch_json(client, f"{self.course_service_url}/api/v1/modules", headers),
                _fetch_json(
                    client,
                    f"{self.activity_service_url}/api/v1/activities?creatorOnly=true",
                    headers,
                ),
                _fetch_json(
                    client,
                    f"{self.progress_service_url}/api/v1/progress/summary/user/{user_id}",
                    headers,
                ),
                _fetch_json(
                    client,
                    f"{self.progress_service_url}/api/v1/progress/activities/user/{user_id}?limit=50",
                    headers,
                ),
            )

        return self.assemble(
            user_id=user_id,
            raw_results=list(raw_results),
            client_context=client_context,
        )
