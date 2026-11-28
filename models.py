"""Typed Pydantic schemas for all 5 stages of the Personalized Recommendation Tool."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class ClientContextPayload(BaseModel):
    """Optional real-time client state used to supplement microservice data."""

    studentName: Optional[str] = None
    email: Optional[str] = None
    gradeLevel: Optional[str] = None
    learningStyle: Optional[str] = None
    difficultyLevel: Optional[str] = None
    preferredSubjects: Optional[List[str]] = None
    starsEarned: Optional[int] = None
    averageScore: Optional[float] = None
    mapActivitiesDone: Optional[int] = None
    practiceActivitiesDone: Optional[int] = None
    currentStreakDays: Optional[int] = None
    subjectProgress: Optional[Dict[str, Any]] = None
    completedMapActivities: Optional[Dict[str, Any]] = None
    recentScores: Optional[List[Dict[str, Any]]] = None
    badges: Optional[List[Dict[str, Any]]] = None
    enrollments: Optional[List[Dict[str, Any]]] = None
    courses: Optional[List[Dict[str, Any]]] = None
    modules: Optional[List[Dict[str, Any]]] = None
    activities: Optional[List[Dict[str, Any]]] = None
    lastScorePercentage: Optional[float] = None
    lastSubject: Optional[str] = None
    lastModuleId: Optional[int] = None
    lastModuleTitle: Optional[str] = None


class CollectedStudentData(BaseModel):
    """Output of Stage 1: Student Data Collection across the 6 existing microservices."""

    userId: int
    collectedAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    userProfile: Dict[str, Any] = Field(default_factory=dict)
    preferences: Dict[str, Any] = Field(default_factory=dict)
    enrollments: List[Dict[str, Any]] = Field(default_factory=list)
    subjects: List[Dict[str, Any]] = Field(default_factory=list)
    courses: List[Dict[str, Any]] = Field(default_factory=list)
    modules: List[Dict[str, Any]] = Field(default_factory=list)
    activities: List[Dict[str, Any]] = Field(default_factory=list)
    progressSummary: Dict[str, Any] = Field(default_factory=dict)
    progressHistory: List[Dict[str, Any]] = Field(default_factory=list)
    clientContext: Optional[ClientContextPayload] = None
    sourceHealth: Dict[str, str] = Field(default_factory=dict)


class SubjectLearningStat(BaseModel):
    subject: str
    masteryPercentage: float = 0.0
    attemptCount: int = 0
    passedCount: int = 0
    averageScore: float = 0.0
    lastScore: Optional[float] = None
    totalTimeSpentMins: int = 0
    trend: Literal["IMPROVING", "STEADY", "NEEDS_ATTENTION", "NOT_STARTED"] = "NOT_STARTED"


class StudentLearningProfile(BaseModel):
    """Output of Stage 2: Unified Student Learning Profile."""

    userId: int
    studentName: str = "Explorer"
    gradeLevel: str = "Grade 4"
    gradeEnum: str = "GRADE_4"
    learningStyle: str = "INTERACTIVE"
    difficultyPreference: str = "ADAPTIVE"
    enrolledCourseIds: List[int] = Field(default_factory=list)
    completedCourseIds: List[int] = Field(default_factory=list)
    pendingCourseIds: List[int] = Field(default_factory=list)
    starsEarned: int = 0
    averageScore: float = 0.0
    mapActivitiesDone: int = 0
    practiceActivitiesDone: int = 0
    currentStreakDays: int = 1
    subjectStats: Dict[str, SubjectLearningStat] = Field(default_factory=dict)
    questionTypeStats: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    earnedBadges: List[str] = Field(default_factory=list)
    lockedBadges: List[str] = Field(default_factory=list)
    completedActivityIds: List[int] = Field(default_factory=list)
    lowScoreActivityIds: List[int] = Field(default_factory=list)
    bestScoreByActivityId: Dict[str, float] = Field(default_factory=dict)


class BadgeOpportunity(BaseModel):
    badgeId: str
    badgeName: str
    icon: str
    requirement: str
    progressText: str
    urgency: float = 0.5


class LearningProfileAnalysis(BaseModel):
    """Output of Stage 3: Learning Profile Analysis."""

    performanceTier: Literal["STARTER", "DEVELOPING", "PROFICIENT", "ADVANCED"] = "STARTER"
    recommendedDifficulty: Literal["EASY", "MEDIUM", "HARD"] = "MEDIUM"
    strongSubjects: List[str] = Field(default_factory=list)
    weakSubjects: List[str] = Field(default_factory=list)
    untouchedSubjects: List[str] = Field(default_factory=list)
    preferredQuestionTypes: List[str] = Field(default_factory=list)
    badgeOpportunities: List[BadgeOpportunity] = Field(default_factory=list)
    insightHeadline: str = ""
    analysisNotes: List[str] = Field(default_factory=list)


class RecommendationCandidate(BaseModel):
    """Output of Stage 4 & 5: Generated and Ranked Recommendation Item."""

    recommendationId: str
    itemType: Literal["COURSE", "ACTIVITY", "AI_PRACTICE", "STUDY_TIP"]
    actionType: Literal[
        "ENROLL",
        "RESUME",
        "PLAY_MAP",
        "RETRY_MAP",
        "GENERATE_PRACTICE",
        "REVIEW_NOTES",
        "EARN_BADGE",
    ]
    title: str
    description: str
    subject: str = "General"
    gradeLevel: str = "Grade 4"
    difficulty: Literal["EASY", "MEDIUM", "HARD"] = "MEDIUM"
    activityType: Optional[str] = None
    courseId: Optional[int] = None
    moduleId: Optional[int] = None
    activityId: Optional[int] = None
    courseTitle: Optional[str] = None
    moduleTitle: Optional[str] = None
    icon: str = "twemoji:sparkles"
    targetPath: str = "/courses"
    navigationState: Dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    tags: List[str] = Field(default_factory=list)
    priorityScore: float = 0.0
    rank: int = 0
    scoreBreakdown: Dict[str, float] = Field(default_factory=dict)


class RecommendationToolOutput(BaseModel):
    """Structured output returned by the Personalized Recommendation Tool to the Java AI Recommendation Service."""

    userId: int
    generatedAt: str
    mascotTip: str
    profile: StudentLearningProfile
    analysis: LearningProfileAnalysis
    recommendations: List[RecommendationCandidate]
    recommendedCourses: List[RecommendationCandidate]
    recommendedActivities: List[RecommendationCandidate]
    studyTips: List[RecommendationCandidate]
    sourceHealth: Dict[str, str]


class RecommendationBundleResponse(RecommendationToolOutput):
    """Persisted or cached recommendation bundle returned to downstream services."""

    cacheHit: bool = False
    storageBackend: str = "sqlite"


class RecommendationFeedbackRequest(BaseModel):
    """Student interaction feedback recorded against a generated recommendation."""

    action: Literal["CLICKED", "STARTED", "COMPLETED", "DISMISSED", "HELPFUL"]
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    comment: Optional[str] = None
