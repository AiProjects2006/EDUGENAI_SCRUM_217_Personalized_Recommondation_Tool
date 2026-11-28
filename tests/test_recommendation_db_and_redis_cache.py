"""Tests for Recommendation DB (MySQL/SQLite) & Redis Cache (TTL + Invalidation)."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models import CollectedStudentData, RecommendationBundleResponse
from pipeline import RecommendationPipeline
from recommendation_db import RecommendationDatabase
from recommendation_generation import RecommendationGenerator
from redis_cache import RecommendationRedisCache


def _build_ranked_output(user_id: int = 42):
    data = CollectedStudentData(
        userId=user_id,
        userProfile={"id": user_id, "firstName": "Nethmi", "lastName": "Perera"},
        preferences={"learningStyle": "VISUAL", "difficultyLevel": "ADAPTIVE"},
        enrollments=[
            {"enrollmentId": 10, "courseId": 101, "status": "ACTIVE", "studentGrade": "Grade 4"},
        ],
        subjects=[
            {"subjectId": 1, "name": "Mathematics"},
            {"subjectId": 2, "name": "ICT"},
        ],
        courses=[
            {"courseId": 101, "subjectId": 1, "title": "Fractions & Decimals", "gradeLevel": "Grade 4", "status": "PUBLISHED"},
            {"courseId": 102, "subjectId": 2, "title": "Digital Tools", "gradeLevel": "Grade 4", "status": "PUBLISHED"},
        ],
        modules=[{"moduleId": 201, "courseId": 101, "title": "Pizza Fractions"}],
        activities=[
            {"activityId": 301, "moduleId": 201, "displayOrder": 1, "title": "Half & Quarter Quiz", "activityType": "MCQ", "difficulty": "MEDIUM", "status": "PUBLISHED", "createdByRole": "CONTENT_CREATOR"},
        ],
        progressSummary={"starsEarned": 25, "mapActivitiesDone": 1, "averageScore": 45.0},
        progressHistory=[
            {"activityId": 301, "moduleId": 201, "subjectName": "Mathematics", "scorePercentage": 45.0, "isPassed": True},
        ],
    )
    pipeline = RecommendationPipeline(generator=RecommendationGenerator(enable_llm=False))
    return data, pipeline, pipeline.run_from_collected(data)


class _FakeRedisClient:
    """Minimal in-memory mock implementing ping/get/setex/delete for Redis tests."""

    def __init__(self, fail_ping: bool = False) -> None:
        self.fail_ping = fail_ping
        self.store: dict[str, tuple[int, str]] = {}
        self.now = 100.0

    def ping(self) -> bool:
        if self.fail_ping:
            raise ConnectionError("Redis unreachable")
        return True

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.store[key] = (ttl, value)
        self._expiry = getattr(self, "_expiry", {})
        self._expiry[key] = self.now + ttl

    def get(self, key: str):
        exp = getattr(self, "_expiry", {}).get(key)
        if exp is None or self.now >= exp:
            self.store.pop(key, None)
            return None
        return self.store[key][1]

    def delete(self, key: str) -> None:
        self.store.pop(key, None)
        getattr(self, "_expiry", {}).pop(key, None)


class RecommendationDbAndCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.sqlite_path = str(Path(self.temp_dir.name) / "rec_test.sqlite")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_sqlite_persistence_dismissal_preservation_and_feedback(self) -> None:
        data, pipeline, output = _build_ranked_output(user_id=42)
        db = RecommendationDatabase(db_type="sqlite", sqlite_path=self.sqlite_path)
        self.assertEqual(db.backend, "sqlite")

        db.save_bundle(output)

        saved_profile = db.get_saved_profile(42)
        self.assertIsNotNone(saved_profile)
        self.assertEqual(saved_profile["profile"]["studentName"], "Nethmi Perera")
        self.assertEqual(saved_profile["storageBackend"], "sqlite")

        saved_recs = db.get_saved_recommendations(42)
        self.assertEqual(len(saved_recs), len(output.recommendations))
        self.assertEqual(saved_recs[0].rank, 1)

        rebuilt_bundle = db.get_saved_bundle(42)
        self.assertIsInstance(rebuilt_bundle, RecommendationBundleResponse)
        self.assertFalse(rebuilt_bundle.cacheHit)

        # Record DISMISSED feedback without explicit user_id -> resolves user 42 from DB
        dismissed_id = output.recommendations[-1].recommendationId
        resolved_uid = db.record_feedback(
            dismissed_id,
            action="DISMISSED",
            rating=2,
            comment="Already completed in class",
        )
        self.assertEqual(resolved_uid, 42)
        self.assertIn(dismissed_id, db.get_dismissed_ids(42))

        fb_rows = db.get_feedback_history(42)
        self.assertEqual(len(fb_rows), 1)
        self.assertEqual(fb_rows[0]["action"], "DISMISSED")
        self.assertEqual(fb_rows[0]["rating"], 2)

        # Regenerating without filtering keeps DISMISSED hidden and sticky in DB
        db.save_bundle(output)
        self.assertIn(dismissed_id, db.get_dismissed_ids(42))
        active_after_regen = [r.recommendationId for r in db.get_saved_recommendations(42)]
        self.assertNotIn(dismissed_id, active_after_regen)

        # Full pipeline honors dismissed_ids from DB
        filtered_output = pipeline.run_from_collected(
            data, dismissed_ids=db.get_dismissed_ids(42)
        )
        self.assertNotIn(
            dismissed_id, [r.recommendationId for r in filtered_output.recommendations]
        )

    def test_mysql_backend_initialization_and_upsert_queries(self) -> None:
        executed_sql: list[str] = []

        class FakeCursor:
            def __init__(self) -> None:
                self._rows: list[tuple[object, ...]] = []

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, sql: str, _params=None) -> None:
                executed_sql.append(" ".join(sql.split()))
                if sql.strip().upper().startswith("SELECT RECOMMENDATION_ID"):
                    self._rows = []

            def fetchall(self):
                return self._rows

            def fetchone(self):
                return None

        class FakeMySQLConnection:
            def cursor(self):
                return FakeCursor()

            def close(self) -> None:
                pass

            def rollback(self) -> None:
                pass

        fake_pymysql = type(
            "FakePyMySQLModule",
            (),
            {"connect": staticmethod(lambda **_kw: FakeMySQLConnection())},
        )()

        with patch.dict(sys.modules, {"pymysql": fake_pymysql}):
            db = RecommendationDatabase(
                db_type="mysql",
                sqlite_path=self.sqlite_path,
                mysql_database="recommendation_db",
            )
            self.assertEqual(db.backend, "mysql")
            _, _, output = _build_ranked_output(user_id=10)
            db.save_bundle(output)
            db.record_feedback("course-101", "COMPLETED", user_id=10, rating=5)

        joined = "\n".join(executed_sql)
        self.assertIn("CREATE DATABASE IF NOT EXISTS `recommendation_db`", joined)
        self.assertIn("ON DUPLICATE KEY UPDATE", joined)
        self.assertIn("INSERT INTO recommendation_feedback", joined)

    def test_redis_cache_ttl_bundle_roundtrip_and_invalidation(self) -> None:
        fake_client = _FakeRedisClient()
        cache = RecommendationRedisCache(ttl_seconds=60, client=fake_client)
        self.assertEqual(cache.backend, "redis")

        _, _, output = _build_ranked_output(user_id=42)
        cache.set_bundle(output, ttl_seconds=30)

        cached = cache.get_bundle(42)
        self.assertIsNotNone(cached)
        self.assertTrue(cached.cacheHit)
        self.assertEqual(cached.userId, 42)
        self.assertEqual(len(cached.recommendations), len(output.recommendations))

        # Invalidating removes both Redis and fallback cache entries
        cache.invalidate(42)
        self.assertIsNone(cache.get_bundle(42))

        # Expired TTL returns None
        cache.set_bundle(output, ttl_seconds=10)
        fake_client.now += 15.0
        with patch("redis_cache.time.monotonic", return_value=1000.0):
            cache._memory_fallback[cache._key(42)] = (999.0, output.model_dump_json())
            self.assertIsNone(cache.get(42))

    def test_redis_cache_memory_fallback_and_expiry_when_redis_unavailable(self) -> None:
        clock = [10.0]
        unreachable_client = _FakeRedisClient(fail_ping=True)

        with patch("redis.Redis", side_effect=ConnectionError("Redis offline")):
            auto_fallback = RecommendationRedisCache(ttl_seconds=5)
            self.assertEqual(auto_fallback.backend, "memory")

        with patch("redis_cache.time.monotonic", side_effect=lambda: clock[0]):
            cache = RecommendationRedisCache(ttl_seconds=5, client=unreachable_client)
            self.assertEqual(cache.backend, "memory")

            cache.set(77, '{"hello": "world"}', ttl_seconds=5)
            self.assertEqual(cache.get(77), '{"hello": "world"}')

            clock[0] = 16.0
            self.assertIsNone(cache.get(77))

            cache.set(77, '{"hello": "again"}', ttl_seconds=30)
            cache.invalidate_users([77])
            self.assertIsNone(cache.get(77))


if __name__ == "__main__":
    unittest.main(verbosity=2)
