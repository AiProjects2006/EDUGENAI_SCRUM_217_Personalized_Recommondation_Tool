"""Tests for Stage 1: Student Data Collection across the 6 existing microservices."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import unittest
import httpx

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models import ClientContextPayload
from student_data_collection import (
    StudentDataCollector,
    is_creator_published_activity,
)


class StudentDataCollectionTests(unittest.TestCase):
    def test_creator_only_activity_filtering(self) -> None:
        self.assertTrue(
            is_creator_published_activity(
                {"activityId": 1, "status": "PUBLISHED", "createdByRole": "CONTENT_CREATOR"}
            )
        )
        self.assertFalse(
            is_creator_published_activity(
                {"activityId": 2, "status": "DRAFT", "createdByRole": "CONTENT_CREATOR"}
            )
        )
        self.assertFalse(
            is_creator_published_activity(
                {"activityId": 3, "status": "PUBLISHED", "createdByRole": "STUDENT"}
            )
        )
        self.assertFalse(
            is_creator_published_activity(
                {"activityId": 4, "status": "PUBLISHED", "description": "AI-generated MCQ quiz"}
            )
        )

    def test_collect_merges_all_six_microservices_and_filters_student_activities(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if ":8081/api/users/42" in url:
                return httpx.Response(200, json={"id": 42, "firstName": "Nethmi", "lastName": "Perera"})
            if ":8084/api/v1/preferences/user/42" in url:
                return httpx.Response(
                    200, json={"preferenceId": 1, "userId": 42, "learningStyle": "VISUAL", "difficultyLevel": "MEDIUM"}
                )
            if ":8084/api/v1/enrollments/user/42" in url:
                return httpx.Response(
                    200, json=[{"enrollmentId": 10, "userId": 42, "courseId": 101, "status": "ACTIVE"}]
                )
            if ":8082/api/v1/subjects" in url:
                return httpx.Response(
                    200, json={"success": True, "message": "ok", "data": [{"subjectId": 1, "name": "Mathematics"}]}
                )
            if ":8082/api/v1/courses" in url:
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "message": "ok",
                        "data": [{"courseId": 101, "subjectId": 1, "title": "Fractions", "status": "PUBLISHED"}],
                    },
                )
            if ":8082/api/v1/modules" in url:
                return httpx.Response(
                    200, json={"success": True, "message": "ok", "data": [{"moduleId": 201, "courseId": 101, "title": "Pizza Fractions"}]}
                )
            if ":8083/api/v1/activities" in url:
                return httpx.Response(
                    200,
                    json=[
                        {"activityId": 301, "moduleId": 201, "status": "PUBLISHED", "createdByRole": "CONTENT_CREATOR", "title": "Creator Quiz"},
                        {"activityId": 302, "moduleId": 201, "status": "PUBLISHED", "createdByRole": "STUDENT", "title": "Student AI Quiz"},
                        {"activityId": 303, "moduleId": 201, "status": "DRAFT", "createdByRole": "CONTENT_CREATOR", "title": "Draft Quiz"},
                    ],
                )
            if ":8088/api/v1/progress/summary/user/42" in url:
                return httpx.Response(
                    200, json={"success": True, "message": "ok", "data": {"userId": 42, "starsEarned": 15}}
                )
            if ":8088/api/v1/progress/activities/user/42" in url:
                return httpx.Response(
                    200, json={"success": True, "message": "ok", "data": [{"recordId": 1, "activityId": 301, "scorePercentage": 80}]}
                )
            return httpx.Response(404)

        collector = StudentDataCollector(transport=httpx.MockTransport(handler))
        data = asyncio.run(collector.collect(user_id=42))

        self.assertEqual(data.userProfile["firstName"], "Nethmi")
        self.assertEqual(data.preferences["learningStyle"], "VISUAL")
        self.assertEqual(len(data.enrollments), 1)
        self.assertEqual(data.courses[0]["subject"], "Mathematics")
        self.assertEqual([a["activityId"] for a in data.activities], [301])
        self.assertEqual(data.progressSummary["starsEarned"], 15)
        self.assertTrue(all(v == "ok" for v in data.sourceHealth.values()))

    def test_client_fallback_when_microservices_fail(self) -> None:
        def failing_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Service offline", request=request)

        ctx = ClientContextPayload(
            studentName="Kasun Silva",
            learningStyle="STEP_BY_STEP",
            difficultyLevel="EASY",
            starsEarned=12,
            courses=[{"courseId": 11, "title": "ICT Basics", "subject": "ICT"}],
            modules=[{"moduleId": 21, "courseId": 11, "title": "Mouse & Keyboard"}],
            activities=[
                {"activityId": 31, "moduleId": 21, "status": "PUBLISHED", "createdByRole": "CONTENT_CREATOR"},
                {"activityId": 32, "moduleId": 21, "status": "PUBLISHED", "createdByRole": "STUDENT"},
            ],
            enrollments=[{"courseId": 11, "status": "ACTIVE"}],
        )

        collector = StudentDataCollector(transport=httpx.MockTransport(failing_handler))
        data = asyncio.run(collector.collect(user_id=99, client_context=ctx))

        self.assertEqual(data.userProfile["firstName"], "Kasun")
        self.assertEqual(data.preferences["learningStyle"], "STEP_BY_STEP")
        self.assertEqual(len(data.courses), 1)
        self.assertEqual([a["activityId"] for a in data.activities], [31])
        self.assertEqual(data.progressSummary["starsEarned"], 12)
        self.assertTrue(all(v == "client_fallback" for v in data.sourceHealth.values()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
