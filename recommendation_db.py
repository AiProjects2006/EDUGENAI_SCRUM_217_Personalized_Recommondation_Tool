"""Recommendation DB persistence (MySQL recommendation_db with SQLite fallback)."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, Iterator, List, Optional, Set
import uuid

from config import settings
from models import (
    LearningProfileAnalysis,
    RecommendationBundleResponse,
    RecommendationCandidate,
    RecommendationToolOutput,
    StudentLearningProfile,
)

log = logging.getLogger(__name__)


class RecommendationDatabase:
    """Stores student learning profiles, ranked recommendations, and feedback events."""

    def __init__(
        self,
        db_type: str = settings.db_type,
        sqlite_path: str = settings.sqlite_db_path,
        mysql_host: str = settings.mysql_host,
        mysql_port: int = settings.mysql_port,
        mysql_user: str = settings.mysql_user,
        mysql_password: str = settings.mysql_password,
        mysql_database: str = settings.mysql_database,
    ) -> None:
        self.db_type = (db_type or "auto").strip().lower()
        self.sqlite_path = sqlite_path
        self.mysql_host = mysql_host
        self.mysql_port = mysql_port
        self.mysql_user = mysql_user
        self.mysql_password = mysql_password
        self.mysql_database = mysql_database
        self.backend = "sqlite"
        self._init_backend()

    @property
    def _ph(self) -> str:
        return "%s" if self.backend == "mysql" else "?"

    def _init_backend(self) -> None:
        if self.db_type in {"auto", "mysql"}:
            try:
                import pymysql  # type: ignore

                bootstrap_conn = pymysql.connect(
                    host=self.mysql_host,
                    port=self.mysql_port,
                    user=self.mysql_user,
                    password=self.mysql_password,
                    connect_timeout=2,
                    autocommit=True,
                )
                try:
                    with bootstrap_conn.cursor() as cur:
                        cur.execute(
                            f"CREATE DATABASE IF NOT EXISTS `{self.mysql_database}` "
                            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                        )
                finally:
                    bootstrap_conn.close()

                db_conn = pymysql.connect(
                    host=self.mysql_host,
                    port=self.mysql_port,
                    user=self.mysql_user,
                    password=self.mysql_password,
                    database=self.mysql_database,
                    connect_timeout=2,
                    autocommit=True,
                )
                try:
                    self._create_mysql_tables(db_conn)
                finally:
                    db_conn.close()

                self.backend = "mysql"
                log.info("Connected to MySQL Recommendation DB (%s)", self.mysql_database)
                return
            except Exception as exc:
                if self.db_type == "mysql":
                    log.warning("Forced MySQL DB unavailable (%s); falling back to SQLite.", exc)
                else:
                    log.info("MySQL unavailable locally (%s); using SQLite Recommendation DB.", exc)

        Path(self.sqlite_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.sqlite_path)
        try:
            self._create_sqlite_tables(conn)
        finally:
            conn.close()
        self.backend = "sqlite"

    def _create_mysql_tables(self, conn: Any) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS student_learning_profiles (
                    user_id BIGINT PRIMARY KEY,
                    grade_level VARCHAR(32),
                    learning_style VARCHAR(64),
                    difficulty_preference VARCHAR(32),
                    performance_tier VARCHAR(32),
                    profile_json LONGTEXT NOT NULL,
                    analysis_json LONGTEXT NOT NULL,
                    mascot_tip TEXT,
                    updated_at VARCHAR(64) NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS recommendations (
                    id VARCHAR(128) PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    recommendation_id VARCHAR(128) NOT NULL,
                    item_type VARCHAR(32) NOT NULL,
                    action_type VARCHAR(32) NOT NULL,
                    title VARCHAR(255) NOT NULL,
                    subject VARCHAR(100),
                    grade_level VARCHAR(32),
                    difficulty VARCHAR(32),
                    priority_score DOUBLE NOT NULL,
                    rank_order INT NOT NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
                    payload_json LONGTEXT NOT NULL,
                    updated_at VARCHAR(64) NOT NULL,
                    INDEX idx_rec_user (user_id)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS recommendation_feedback (
                    feedback_id VARCHAR(64) PRIMARY KEY,
                    user_id BIGINT,
                    recommendation_id VARCHAR(128) NOT NULL,
                    action VARCHAR(32) NOT NULL,
                    rating INT NULL,
                    comment TEXT NULL,
                    created_at VARCHAR(64) NOT NULL,
                    INDEX idx_fb_user (user_id)
                )
                """
            )

    def _create_sqlite_tables(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS student_learning_profiles (
                user_id INTEGER PRIMARY KEY,
                grade_level TEXT,
                learning_style TEXT,
                difficulty_preference TEXT,
                performance_tier TEXT,
                profile_json TEXT NOT NULL,
                analysis_json TEXT NOT NULL,
                mascot_tip TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS recommendations (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                recommendation_id TEXT NOT NULL,
                item_type TEXT NOT NULL,
                action_type TEXT NOT NULL,
                title TEXT NOT NULL,
                subject TEXT,
                grade_level TEXT,
                difficulty TEXT,
                priority_score REAL NOT NULL,
                rank_order INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_rec_user ON recommendations(user_id)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS recommendation_feedback (
                feedback_id TEXT PRIMARY KEY,
                user_id INTEGER,
                recommendation_id TEXT NOT NULL,
                action TEXT NOT NULL,
                rating INTEGER,
                comment TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_fb_user ON recommendation_feedback(user_id)")
        conn.commit()

    def _connect(self) -> Any:
        if self.backend == "mysql":
            import pymysql  # type: ignore

            return pymysql.connect(
                host=self.mysql_host,
                port=self.mysql_port,
                user=self.mysql_user,
                password=self.mysql_password,
                database=self.mysql_database,
                connect_timeout=2,
                autocommit=True,
            )
        return sqlite3.connect(self.sqlite_path)

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        conn = self._connect()
        try:
            yield conn
            if self.backend == "sqlite" and hasattr(conn, "commit"):
                conn.commit()
        except Exception:
            if hasattr(conn, "rollback"):
                conn.rollback()
            raise
        finally:
            conn.close()

    def get_dismissed_ids(self, user_id: int) -> Set[str]:
        """Return recommendation IDs previously marked DISMISSED for the student."""
        sql = (
            f"SELECT recommendation_id FROM recommendations "
            f"WHERE user_id = {self._ph} AND status = 'DISMISSED'"
        )
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute(sql, (user_id,))
            rows = cur.fetchall()
        return {str(row[0]) for row in rows}

    def save_bundle(self, bundle: RecommendationToolOutput) -> None:
        """Persist profile, analysis, and ranked recommendations while preserving DISMISSED rows."""
        now = datetime.now(timezone.utc).isoformat()
        ph = self._ph
        profile_json = bundle.profile.model_dump_json()
        analysis_json = bundle.analysis.model_dump_json()

        with self._connection() as conn:
            cur = conn.cursor()
            if self.backend == "mysql":
                cur.execute(
                    """
                    INSERT INTO student_learning_profiles (
                        user_id, grade_level, learning_style, difficulty_preference,
                        performance_tier, profile_json, analysis_json, mascot_tip, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        grade_level=VALUES(grade_level),
                        learning_style=VALUES(learning_style),
                        difficulty_preference=VALUES(difficulty_preference),
                        performance_tier=VALUES(performance_tier),
                        profile_json=VALUES(profile_json),
                        analysis_json=VALUES(analysis_json),
                        mascot_tip=VALUES(mascot_tip),
                        updated_at=VALUES(updated_at)
                    """,
                    (
                        bundle.userId,
                        bundle.profile.gradeLevel,
                        bundle.profile.learningStyle,
                        bundle.profile.difficultyPreference,
                        bundle.analysis.performanceTier,
                        profile_json,
                        analysis_json,
                        bundle.mascotTip,
                        now,
                    ),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO student_learning_profiles (
                        user_id, grade_level, learning_style, difficulty_preference,
                        performance_tier, profile_json, analysis_json, mascot_tip, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET
                        grade_level=excluded.grade_level,
                        learning_style=excluded.learning_style,
                        difficulty_preference=excluded.difficulty_preference,
                        performance_tier=excluded.performance_tier,
                        profile_json=excluded.profile_json,
                        analysis_json=excluded.analysis_json,
                        mascot_tip=excluded.mascot_tip,
                        updated_at=excluded.updated_at
                    """,
                    (
                        bundle.userId,
                        bundle.profile.gradeLevel,
                        bundle.profile.learningStyle,
                        bundle.profile.difficultyPreference,
                        bundle.analysis.performanceTier,
                        profile_json,
                        analysis_json,
                        bundle.mascotTip,
                        now,
                    ),
                )

            cur.execute(
                f"SELECT recommendation_id FROM recommendations WHERE user_id = {ph} AND status = 'DISMISSED'",
                (bundle.userId,),
            )
            dismissed_ids = {str(row[0]) for row in cur.fetchall()}

            cur.execute(
                f"DELETE FROM recommendations WHERE user_id = {ph} AND status != 'DISMISSED'",
                (bundle.userId,),
            )

            insert_sql = (
                "INSERT INTO recommendations (id, user_id, recommendation_id, item_type, action_type, "
                "title, subject, grade_level, difficulty, priority_score, rank_order, status, "
                f"payload_json, updated_at) VALUES ({', '.join([ph] * 14)})"
            )
            for item in bundle.recommendations:
                if item.recommendationId in dismissed_ids:
                    continue
                row_id = f"{bundle.userId}:{item.recommendationId}"
                row_params = (
                    row_id,
                    bundle.userId,
                    item.recommendationId,
                    item.itemType,
                    item.actionType,
                    item.title,
                    item.subject,
                    item.gradeLevel,
                    item.difficulty,
                    item.priorityScore,
                    item.rank,
                    "ACTIVE",
                    item.model_dump_json(),
                    now,
                )
                if self.backend == "mysql":
                    cur.execute(
                        insert_sql
                        + " ON DUPLICATE KEY UPDATE priority_score=VALUES(priority_score), "
                        "rank_order=VALUES(rank_order), payload_json=VALUES(payload_json), "
                        "status=IF(status='DISMISSED', 'DISMISSED', VALUES(status)), "
                        "updated_at=VALUES(updated_at)",
                        row_params,
                    )
                else:
                    cur.execute(insert_sql.replace("INSERT INTO", "INSERT OR IGNORE INTO"), row_params)

    def get_saved_profile(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Load persisted student profile, analysis, and mascot insight if present."""
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT profile_json, analysis_json, mascot_tip, updated_at "
                f"FROM student_learning_profiles WHERE user_id = {self._ph}",
                (user_id,),
            )
            row = cur.fetchone()
        if not row:
            return None
        return {
            "userId": user_id,
            "profile": json.loads(row[0]),
            "analysis": json.loads(row[1]),
            "mascotTip": row[2],
            "updatedAt": row[3],
            "storageBackend": self.backend,
        }

    def get_saved_recommendations(
        self,
        user_id: int,
        include_dismissed: bool = False,
    ) -> List[RecommendationCandidate]:
        """Load ordered recommendation candidates for a student from storage."""
        status_clause = "" if include_dismissed else " AND status != 'DISMISSED'"
        sql = (
            f"SELECT payload_json FROM recommendations "
            f"WHERE user_id = {self._ph}{status_clause} ORDER BY rank_order ASC"
        )
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute(sql, (user_id,))
            rows = cur.fetchall()
        return [RecommendationCandidate.model_validate_json(row[0]) for row in rows]

    def get_saved_bundle(self, user_id: int) -> Optional[RecommendationBundleResponse]:
        """Reconstruct a complete persisted RecommendationBundleResponse for cache-miss reads."""
        saved_profile = self.get_saved_profile(user_id)
        if not saved_profile:
            return None

        recs = self.get_saved_recommendations(user_id)
        profile = StudentLearningProfile.model_validate(saved_profile["profile"])
        analysis = LearningProfileAnalysis.model_validate(saved_profile["analysis"])
        return RecommendationBundleResponse(
            userId=user_id,
            generatedAt=saved_profile["updatedAt"],
            mascotTip=saved_profile["mascotTip"] or "",
            profile=profile,
            analysis=analysis,
            recommendations=recs,
            recommendedCourses=[r for r in recs if r.itemType == "COURSE"][:6],
            recommendedActivities=[r for r in recs if r.itemType in {"ACTIVITY", "AI_PRACTICE"}][:8],
            studyTips=[r for r in recs if r.itemType == "STUDY_TIP"][:4],
            sourceHealth={"recommendationDb": self.backend},
            cacheHit=False,
            storageBackend=self.backend,
        )

    def record_feedback(
        self,
        recommendation_id: str,
        action: str,
        user_id: Optional[int] = None,
        rating: Optional[int] = None,
        comment: Optional[str] = None,
    ) -> Optional[int]:
        """Record interaction feedback and update recommendation status cleanly."""
        now = datetime.now(timezone.utc).isoformat()
        ph = self._ph
        feedback_id = str(uuid.uuid4())
        resolved_uid = user_id

        with self._connection() as conn:
            cur = conn.cursor()
            if resolved_uid is None:
                cur.execute(
                    f"SELECT user_id FROM recommendations WHERE recommendation_id = {ph} LIMIT 1",
                    (recommendation_id,),
                )
                row = cur.fetchone()
                if row:
                    resolved_uid = int(row[0])

            if resolved_uid is not None:
                cur.execute(
                    f"UPDATE recommendations SET status = {ph}, updated_at = {ph} "
                    f"WHERE user_id = {ph} AND recommendation_id = {ph} AND status != 'DISMISSED'",
                    (action, now, resolved_uid, recommendation_id),
                )
            else:
                cur.execute(
                    f"UPDATE recommendations SET status = {ph}, updated_at = {ph} "
                    f"WHERE recommendation_id = {ph} AND status != 'DISMISSED'",
                    (action, now, recommendation_id),
                )

            cur.execute(
                "INSERT INTO recommendation_feedback "
                "(feedback_id, user_id, recommendation_id, action, rating, comment, created_at) "
                f"VALUES ({', '.join([ph] * 7)})",
                (feedback_id, resolved_uid, recommendation_id, action, rating, comment, now),
            )

        return resolved_uid

    def get_feedback_history(self, user_id: int) -> List[Dict[str, Any]]:
        """Return persisted feedback events for a student ordered newest first."""
        sql = (
            f"SELECT feedback_id, user_id, recommendation_id, action, rating, comment, created_at "
            f"FROM recommendation_feedback WHERE user_id = {self._ph} ORDER BY created_at DESC"
        )
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute(sql, (user_id,))
            rows = cur.fetchall()
        return [
            {
                "feedbackId": row[0],
                "userId": row[1],
                "recommendationId": row[2],
                "action": row[3],
                "rating": row[4],
                "comment": row[5],
                "createdAt": row[6],
            }
            for row in rows
        ]
