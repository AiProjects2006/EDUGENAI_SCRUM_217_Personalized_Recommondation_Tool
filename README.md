# EDUGENAI SCRUM-217: Personalized Recommendation Tool

5-stage AI-Powered Personalized Recommendation Tool aligned with the Personalized Recommendation Tool Architecture.
*(Note: The downstream **AI Recommendation Service**, **Recommendation DB**, and **Redis Cache** are implemented separately in Java Spring Boot.)*

## Architecture Files

- `config.py`: Existing microservice URLs (`:8081`–`:8088`), HTTP timeout, and optional LLM settings.
- `models.py`: Typed Pydantic schemas for all 5 pipeline stages.
- `student_data_collection.py`: **Stage 1 — Student Data Collection** (async collectors for User, Course, Activity, Enrollment & Preferences, Progress Tracking, plus client fallback and creator-only activity filtering).
- `student_learning_profile.py`: **Stage 2 — Student Learning Profile**
- `learning_profile_analysis.py`: **Stage 3 — Learning Profile Analysis**
- `recommendation_generation.py`: **Stage 4 — Recommendation Generation**
- `recommendation_ranking.py`: **Stage 5 — Recommendation Ranking**

## Feature Branches

1. `feature/setup-and-models`: Foundation (`requirements.txt`, config/env settings, Pydantic schemas, project layout, `Dockerfile`)
2. `feature/student-data-collection`: Stage 1 — Student Data Collection
3. `feature/student-learning-profile`: Stage 2 — Student Learning Profile
4. `feature/learning-profile-analysis`: Stage 3 — Learning Profile Analysis
5. `feature/recommendation-generation`: Stage 4 — Recommendation Generation
6. `feature/recommendation-ranking`: Stage 5 — Recommendation Ranking

## Run Tests

```powershell
& "..\EDUGENAI_SCRUM_53_Multi_Agent_Setup\.venv\Scripts\python.exe" -m unittest discover -s tests -v
```
